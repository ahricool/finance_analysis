"""Binance public spot transport only; no strategy or stock-provider integration."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from websockets.asyncio.client import connect

from finance_analysis.crypto.config import CryptoConfig
from finance_analysis.crypto.models import Kline


def from_ms(value) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, timezone.utc)


def parse_rest(row, as_of: datetime) -> Kline:
    start = from_ms(row[0])
    end = from_ms(int(row[6]) + 1)
    return Kline(
        start,
        end,
        *(Decimal(str(row[i])) for i in (1, 2, 3, 4, 5, 7)),
        int(row[8]),
        Decimal(str(row[9])),
        Decimal(str(row[10])),
        closed=end <= as_of,
    )


def parse_ws(message: str) -> Kline:
    data = json.loads(message)
    if data.get("e") != "kline" or data.get("s") != "BTCUSDT":
        raise ValueError("Unexpected Binance event")
    row = data["k"]
    if row["s"] != "BTCUSDT" or row["i"] != "1m" or not isinstance(row["x"], bool):
        raise ValueError("Unexpected Binance kline")
    end = from_ms(int(row["T"]) + 1)
    if row["x"] and from_ms(data["E"]) < end - timedelta(milliseconds=1):
        raise ValueError("Closed kline precedes its boundary")
    return Kline(
        from_ms(row["t"]),
        end,
        *(Decimal(str(row[k])) for k in ("o", "h", "l", "c", "v", "q")),
        int(row["n"]),
        Decimal(str(row["V"])),
        Decimal(str(row["Q"])),
        closed=row["x"],
    )


class BinanceClient:
    def __init__(self, config: CryptoConfig, http=None):
        self.config = config
        self.http = http or httpx.AsyncClient(base_url=config.rest_base_url.rstrip("/"), timeout=10)

    async def close(self):
        await self.http.aclose()

    async def _get(self, path, params=None):
        for attempt in range(3):
            try:
                response = await self.http.get(path, params=params)
                response.raise_for_status()
                result = response.json()
                if isinstance(result, dict) and "code" in result:
                    raise ValueError("Binance returned an error")
                return result
            except (httpx.HTTPError, ValueError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)

    async def server_time(self):
        return from_ms((await self._get("/api/v3/time"))["serverTime"])

    async def klines(self, *, start=None, end=None, limit=5, as_of=None):
        params = {"symbol": "BTCUSDT", "interval": "1m", "limit": limit}
        if start is not None:
            params["startTime"] = int(start.timestamp() * 1000)
        if end is not None:
            params["endTime"] = int(end.timestamp() * 1000) - 1
        now = as_of or await self.server_time()
        rows = await self._get("/api/v3/klines", params)
        if not isinstance(rows, list):
            raise ValueError("Invalid Binance kline response")
        return sorted((parse_rest(row, now) for row in rows), key=lambda row: row.open_time)

    def websocket(self):
        return connect(
            self.config.ws_base_url.rstrip("/") + "/ws/btcusdt@kline_1m",
            open_timeout=10,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_queue=32,
        )

    async def receive(self, socket):
        return parse_ws(await asyncio.wait_for(socket.recv(), self.config.ws_timeout_seconds))

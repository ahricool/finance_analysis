"""Binance public spot transport only; no strategy or stock-provider integration."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from finance_analysis.crypto.config import CryptoConfig
from finance_analysis.crypto.models import Kline


def from_ms(value) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, timezone.utc)


def parse_rest(row, as_of: datetime, interval: str) -> Kline:
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
        interval=interval,
    )


class BinanceClient:
    def __init__(self, config: CryptoConfig, http=None):
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

    async def klines(self, *, interval: str, end: datetime, limit: int):
        if interval not in ("15m", "1h"):
            raise ValueError("Strategy only uses 15m/1h candles")
        candles = []
        cursor = end
        while len(candles) < limit:
            size = min(1000, limit - len(candles))
            rows = await self._get(
                "/api/v3/klines",
                {
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "limit": size,
                    "endTime": int(cursor.timestamp() * 1000) - 1,
                },
            )
            if not isinstance(rows, list):
                raise ValueError("Invalid Binance kline response")
            page = sorted((parse_rest(row, end, interval) for row in rows), key=lambda row: row.open_time)
            page = [row for row in page if row.closed and row.close_time <= cursor]
            candles = page + candles
            if len(page) < size:
                break
            following = page[0].open_time
            if following >= cursor:
                raise ValueError("Binance history did not advance")
            cursor = following
        return candles

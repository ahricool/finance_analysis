"""Public Binance USD-M market data; no trading endpoints."""
from datetime import datetime, timezone
import asyncio
import time
import math
import logging

import httpx

from finance_analysis.config.env_parsing import env_str
from finance_analysis.core.retry import retry_async

logger = logging.getLogger(__name__)


def from_ms(value) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, timezone.utc)


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite market data")
    return result


def parse_bar(row):
    bar = dict(zip(("open", "high", "low", "close", "volume", "turnover"),
                   (number(row[index]) for index in (1, 2, 3, 4, 5, 7)), strict=True))
    if not 0 < bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
        raise ValueError("Invalid OHLC")
    if min(bar["volume"], bar["turnover"]) < 0:
        raise ValueError("Invalid volume")
    return {"timestamp": int(row[0]), **bar}


class MarketCooldown(RuntimeError):
    """The exchange requested an IP-wide pause."""


class BinanceClient:
    def __init__(self, http=None):
        self._request_lock = asyncio.Lock()
        self._stats_after = self._public_after = self._blocked_until = 0.0
        self.http = http or httpx.AsyncClient(
            base_url=env_str("BINANCE_FUTURES_REST_BASE_URL", "https://fapi.binance.com"), timeout=10,
        )

    async def close(self):
        await self.http.aclose()

    async def market_get(self, path, params=None, *, private_stats=False):
        headers = {}
        if private_stats:
            if path not in ("/futures/data/topLongShortAccountRatio", "/futures/data/topLongShortPositionRatio"):
                raise PermissionError("Unexpected keyed market-data route")
            base = self.http.base_url
            key = env_str("BINANCE_FUTURES_MARKET_DATA_KEY")
            if not key or (base.scheme, base.host, base.port) != ("https", "fapi.binance.com", None):
                raise PermissionError("Dedicated USD-M market-data key unavailable")
            headers["X-MBX-APIKEY"] = key
        async with self._request_lock:
            stats = path.startswith("/futures/data/")
            after = self._stats_after if stats else self._public_after
            await asyncio.sleep(max(0, after - time.monotonic()))
            if time.monotonic() < self._blocked_until:
                raise MarketCooldown("Binance IP cooldown")
            if stats:
                self._stats_after = time.monotonic() + 0.5
            else:
                # At most two public requests/s. The largest backfill page weighs 10.
                self._public_after = time.monotonic() + 0.5
        response = await self.http.get(path, params=params, headers=headers, follow_redirects=False)
        if response.status_code in (418, 429):
            seconds = int(response.headers.get("Retry-After", 300))
            self._blocked_until = max(self._blocked_until, time.monotonic() + max(1, seconds))
        response.raise_for_status()
        return response.json()

    async def _get(self, path, params=None):
        async def request():
            return await self.market_get(path, params)
        return await retry_async(request)

    async def server_time(self):
        return from_ms((await self._get("/fapi/v1/time"))["serverTime"])

    async def exchange_info(self):
        return await self._get("/fapi/v1/exchangeInfo")

    async def contracts(self):
        data = await self.exchange_info()
        return [
            {
                "symbol": item["symbol"], "category": item.get("underlyingType") or "其他",
                "base_asset": item.get("baseAsset"),
            }
            for item in data["symbols"]
            if item["contractType"] in {"PERPETUAL", "TRADIFI_PERPETUAL"} and item["status"] == "TRADING"
            and item["quoteAsset"] == "USDT" and item["marginAsset"] == "USDT"
        ]

    async def quotes(self):
        tickers = await self._get("/fapi/v1/ticker/24hr")
        rates = {}
        try:
            funding = await self._get("/fapi/v1/premiumIndex")
            for item in funding:
                try:
                    rates[item["symbol"]] = number(item["lastFundingRate"])
                except (KeyError, TypeError, ValueError):
                    continue
        except (httpx.HTTPError, TypeError, ValueError):
            logger.warning("USD-M funding rates unavailable", exc_info=True)
        quotes = {}
        for item in tickers:
            try:
                quotes[item["symbol"]] = {
                    "price": number(item["lastPrice"]), "change_pct": number(item["priceChangePercent"]),
                    "turnover": number(item["quoteVolume"]), "funding_rate": rates.get(item["symbol"]),
                    "timestamp": int(item["closeTime"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
        return quotes

    async def klines(self, symbol, interval, start, limit=1000, end=None):
        params = {"symbol": symbol, "interval": interval, "startTime": start, "limit": limit}
        if end is not None:
            params["endTime"] = end
        rows = await self._get("/fapi/v1/klines", params)
        period = {"1m": 60_000, "1d": 86_400_000}[interval]
        result = {}
        for row in rows:
            bar = parse_bar(row)
            timestamp = bar["timestamp"]
            if (timestamp % period or int(row[6]) != timestamp + period - 1 or timestamp < start
                    or (end is not None and timestamp > end)):
                raise ValueError("Invalid Binance candle boundary")
            result[timestamp] = bar
        return [result[key] for key in sorted(result)]

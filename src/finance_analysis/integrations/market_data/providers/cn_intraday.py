"""Free, bounded CN OHLC minute feeds. Never synthesize candles from quote samples."""

import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import time as day_time
from datetime import timedelta, timezone
from functools import partial
from threading import Lock
from time import monotonic, sleep
from zoneinfo import ZoneInfo

import requests

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.bounded_requests import bounded_results
from finance_analysis.integrations.market_data.models import Adjustment, BatchBarResult, Market, MarketBar
from finance_analysis.integrations.market_data.normalizer import canonical_symbol, infer_market
from finance_analysis.integrations.market_data.request_budget import (
    BudgetExhausted,
    check_budget,
    remaining_seconds,
    request_budget,
)
from finance_analysis.integrations.market_data.validator import validate_bars

CN_TZ = ZoneInfo("Asia/Shanghai")
WORKERS = 3
_EXECUTOR = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="cn-minute")


class _Pacer:
    """One request start per second per source in this process, across service instances."""

    def __init__(self):
        self.lock = Lock()
        self.last = float("-inf")

    def wait(self):
        with self.lock:
            check_budget()
            delay = max(0, self.last + 1 - monotonic())
            remaining = remaining_seconds()
            if remaining is not None and remaining < delay + 1:
                raise BudgetExhausted()
            if delay:
                sleep(delay)
            check_budget()
            self.last = monotonic()


_PACERS = {source: _Pacer() for source in ("sina_intraday", "tencent_intraday")}


def _get(source, url, params):
    _PACERS[source].wait()
    remaining = remaining_seconds()
    timeout = min(6.0, remaining / 2) if remaining is not None else 6.0
    response = requests.get(url, params=params, timeout=(min(2, timeout), timeout))
    response.raise_for_status()
    return response


def _number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite minute value")
    return result


class CnIntradayProvider:
    def __init__(self, source, fetch_rows=None):
        if source not in _PACERS:
            raise ValueError("unknown CN minute source")
        self.name = source
        self.fetch_rows = fetch_rows or self._fetch_rows

    def fetch_minute_bars(self, request):
        remaining = remaining_seconds()
        # Do not let a slow primary consume the fallback's entire batch deadline.
        primary_budget = remaining * 0.6 if remaining is not None and self.name == "sina_intraday" else None
        with request_budget(primary_budget):
            return self._fetch_minute_bars(request)

    def _fetch_minute_bars(self, request):
        if request.interval != "1m":
            raise ValueError("CN intraday feeds only support 1m")
        result = BatchBarResult()
        calls = {symbol: partial(self._fetch_symbol, symbol, request) for symbol in request.symbols}
        for symbol, bars, error in bounded_results(calls, _EXECUTOR, WORKERS):
            if error is not None:
                result.failed_symbols[symbol] = str(error)
                result.request_errors[symbol] = str(error)
            elif bars:
                result.data[symbol] = bars
                result.providers_used[symbol] = self.name
            else:
                result.missing_symbols.append(symbol)
        result.fetched_at = utc_now()
        return result

    def _fetch_rows(self, symbol):
        code, exchange = symbol.split(".")
        prefixed = exchange.lower() + code
        if self.name == "sina_intraday":
            response = _get(
                self.name,
                "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData",
                {"symbol": prefixed, "scale": "1", "ma": "no", "datalen": "320"},
            )
            # The public endpoint wraps JSON in JSONP; do not execute its response.
            rows = json.loads(response.text.split("=(", 1)[1].rsplit(");", 1)[0])
        else:
            payload = _get(
                self.name, "https://ifzq.gtimg.cn/appstock/app/kline/mkline", {"param": f"{prefixed},m1,,320"}
            ).json()
            if payload.get("code") != 0:
                raise ValueError("Tencent minute request failed")
            rows = payload["data"][prefixed]["m1"]
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise ValueError("invalid minute response")
        return rows

    def _fetch_symbol(self, symbol, request):
        symbol = canonical_symbol(symbol)
        if infer_market(symbol) is not Market.CN:
            raise ValueError("CN intraday feeds only support CN symbols")
        if self.name == "tencent_intraday" and symbol.endswith(".BJ"):
            raise ValueError("Tencent has no verified BJ minute candles")
        bars = {}
        for row in self.fetch_rows(symbol):
            if self.name == "sina_intraday":
                end = datetime.fromisoformat(row["day"]).replace(tzinfo=CN_TZ).astimezone(timezone.utc)
                values = [row[key] for key in ("open", "high", "low", "close", "volume")]
                amount = None if row.get("amount") in (None, "") else _number(row["amount"])
                multiplier = 1
            else:
                end = datetime.strptime(row[0], "%Y%m%d%H%M").replace(tzinfo=CN_TZ).astimezone(timezone.utc)
                values = [row[1], row[3], row[4], row[2], row[5]]
                amount = None  # Tencent's trailing field is turnover rate, not traded amount.
                multiplier = 1 if symbol.startswith(("688", "689")) else 100
            start = end - timedelta(minutes=1)
            local = start.astimezone(CN_TZ)
            # Both sources label the interval END. Exclude the separate 09:30 auction row.
            regular = day_time(9, 30) <= local.time() < day_time(11, 30) or day_time(13) <= local.time() < day_time(15)
            if not regular or not request.start_time <= start < request.end_time:
                continue
            if not request.include_incomplete and end > request.end_time:
                continue
            o, h, low, close, volume = map(_number, values)
            if volume < 0:
                raise ValueError("negative minute volume")
            bar = MarketBar(
                symbol,
                Market.CN,
                "1m",
                local.date(),
                start,
                o,
                h,
                low,
                close,
                round(volume * multiplier),
                amount,
                "CNY",
                Adjustment.RAW,
                self.name,
                bar_start=start,
                bar_end=end,
            )
            validate_bars([bar])
            bars[start] = bar
        return [bars[key] for key in sorted(bars)]

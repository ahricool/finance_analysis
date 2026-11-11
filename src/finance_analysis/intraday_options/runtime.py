"""Latest-only Redis publication and cache-only reading. No historical persistence."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from finance_analysis.core.time import utc_now
from finance_analysis.intraday_options.config import CONFIG, SYMBOLS, VERSION, WINDOWS
from finance_analysis.intraday_options.scoring import calculate, closed_session_bars
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import cache_ttl, display_day, in_session, session_bounds

logger = logging.getLogger(__name__)


def result_key(symbol: str) -> str:
    return f"rt:intraday-options:{VERSION}:{symbol}"


class Publisher:
    """Publish changed scoring inputs, independent of browser connections."""

    def __init__(self, repository):
        self.repository = repository
        self.published: dict[str, datetime] = {}
        self._published_inputs: dict[str, tuple] = {}

    async def publish(self, symbol, bars, now):
        if symbol not in SYMBOLS:
            return
        # Avoid computing again for quote/unconfirmed-candle updates.
        closed = closed_session_bars(symbol, bars, now)
        if not closed:
            return
        latest = closed[-1].bar_time
        previous = self.published.get(symbol)
        if previous is not None and latest < previous:
            return
        # Compare values, not CandleState identity or receipt time: warmup can replace
        # objects, and closed candles can be mutated/revised without advancing time.
        # Only the trailing scoring horizon matters; timestamps capture missing bars.
        start = latest - timedelta(minutes=max(WINDOWS) - 1)
        inputs = tuple(
            (bar.bar_time, bar.open, bar.high, bar.low, bar.close, bar.volume >= 0, bar.partial, bar.sampled)
            for bar in closed
            if bar.bar_time >= start
        )
        if latest == previous and inputs == self._published_inputs.get(symbol):
            return
        result = calculate(symbol, closed, now)
        if result is None:
            return
        day = market_trading_date(datetime.fromisoformat(result["as_of"]) - timedelta(minutes=1), "US")
        await self.repository.redis.set(
            result_key(symbol), json.dumps(result, allow_nan=False), ex=cache_ttl("US", day, now)
        )
        # Failed writes must remain retryable with the same input.
        self.published[symbol] = latest
        self._published_inputs[symbol] = inputs

    async def run(self, bars_by_symbol, stop_event):
        while not stop_event.is_set():
            now = utc_now()
            for symbol in SYMBOLS:
                try:
                    await self.publish(symbol, list(bars_by_symbol.get(symbol, ())), now)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("日内期权趋势缓存更新失败: %s", symbol, exc_info=True)
            await asyncio.sleep(5)


def session_context(now):
    day = display_day("US", now)
    today = market_trading_date(now, "US")
    bounds = session_bounds("US", today)
    status = "open" if in_session("US", now) else "preopen" if bounds and now < bounds[0] else "closed"
    return day, status


def data_status(result, now, day, market_status):
    if result is None or result.get("trading_date") != day.isoformat() or result.get("version") != VERSION:
        return "waiting"
    as_of = datetime.fromisoformat(result["as_of"])
    if as_of > now + timedelta(seconds=1):
        return "invalid_time"
    bounds = session_bounds("US", day)
    # After close, compare against the closing boundary, not the advancing wall clock.
    reference = min(now, bounds[1]) if bounds else now
    expected = (now - timedelta(seconds=CONFIG.close_grace_seconds)).replace(second=0, microsecond=0)
    if bounds:
        expected = min(expected, bounds[1])
    if as_of < expected or (reference - as_of).total_seconds() > CONFIG.stale_seconds:
        return "delayed"
    if any(w["data_status"] == "gap" for w in result["windows"]):
        return "gap"
    if any(w["data_status"] == "warming" for w in result["windows"]):
        return "warming"
    return "ready"


async def read_snapshot(repository, names, now):
    day, market_status = session_context(now)

    async def read_row(symbol):
        raw, quote, subscription = await asyncio.gather(
            repository.redis.get(result_key(symbol)), repository.get_quote(symbol), repository.get_subscription(symbol)
        )
        result = json.loads(raw) if raw else None
        if result and (result.get("trading_date") != day.isoformat() or result.get("version") != VERSION):
            result = None
        status = data_status(result, now, day, market_status)
        issues = []
        if symbol not in names:
            issues.append("主数据未识别，保留原代码")
        if subscription and subscription.get("status") == "ERROR":
            issues.append("行情采集异常")
        price = change = quote_time = None
        quote_status = "missing"
        if quote and quote.trading_date == day and quote.last_price is not None and quote.last_price > 0:
            price = float(quote.last_price)
            if quote.pre_close is not None and quote.pre_close > 0:
                change = (float(quote.last_price / quote.pre_close) - 1) * 100
            quote_time = quote.event_time
            if quote.event_time is None or quote.received_at is None or quote.timestamp_kind == "received":
                quote_status = "invalid_time"
            elif max(quote.event_time, quote.received_at) > now + timedelta(seconds=30):
                quote_status = "invalid_time"
            elif market_status == "open" and min(quote.event_time, quote.received_at) < now - timedelta(seconds=30):
                quote_status = "delayed"
            else:
                quote_status = "ready"
        return {
            "symbol": symbol,
            "name": names.get(symbol),
            "last_price": price,
            "change_pct": change,
            "quote_time": quote_time,
            "quote_status": quote_status,
            "data_status": status,
            "issues": issues,
            "result": result,
        }

    rows = await asyncio.gather(*(read_row(symbol) for symbol in SYMBOLS))
    return {"trading_date": day, "market_status": market_status, "generated_at": now, "version": VERSION, "items": rows}

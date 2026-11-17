"""Bounded worker scheduling. Async Redis remains exclusively on its owning loop."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import logging

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.intraday_simulation import process
from finance_analysis.intraday_options.config import SYMBOLS
from finance_analysis.intraday_options.scoring import calculate, closed_session_bars
from finance_analysis.intraday_options.simulation import CONFIG
from finance_analysis.market_stream.session import cache_ttl
from finance_analysis.market_stream.config import market_trading_date

logger = logging.getLogger(__name__)


def relative_strength(symbol, bars, benchmark, now):
    result = []
    left = {
        b.bar_time: b
        for b in closed_session_bars(symbol, bars, now)
        if b.is_valid() and not b.partial and not b.sampled
    }
    right = {
        b.bar_time: b
        for b in closed_session_bars("QQQ.US", benchmark, now)
        if b.is_valid() and not b.partial and not b.sampled
    }
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    for minutes in (5, 15, 30):
        times = [end - timedelta(minutes=i) for i in range(minutes)]
        valid = symbol != "QQQ.US" and all(t in left and t in right for t in times)
        start = times[-1]
        value = (
            (
                (float(left[end].close) / float(left[start].open) - float(right[end].close) / float(right[start].open))
                * 100
            )
            if valid
            else None
        )
        result.append(
            dict(
                minutes=minutes,
                value=value,
                start=start.isoformat(),
                end=(end + timedelta(minutes=1)).isoformat(),
                reason=(
                    "同时间区间收益差，百分点"
                    if valid
                    else "不适用" if symbol == "QQQ.US" else "标的或QQQ分钟数据缺失/未对齐"
                ),
            )
        )
    return result


async def run(repository, bars_by_symbol, stop_event):
    from finance_analysis.intraday_options.runtime import result_key

    pool = ThreadPoolExecutor(max_workers=CONFIG.workers, thread_name_prefix="intraday-simulation")
    pending = {}
    cache = {}

    def compute(symbol, bars, benchmark, quote, now):
        now = utc_now()  # Queue wait must not make an old quote look fresh.
        closed = closed_session_bars(symbol, bars, now)
        # All relevant OHLCV/validity revisions invalidate shape cache.
        signature = tuple((b.bar_time, b.open, b.high, b.low, b.close, b.volume, b.partial, b.sampled) for b in closed)
        prior = cache.get(symbol)
        result = prior[1] if prior and prior[0] == signature else calculate(symbol, closed, now) if closed else None
        if result is not None and (not prior or prior[0] != signature):
            from finance_analysis.intraday_options.structure import pivots

            result["execution_pivots"] = [
                p
                for p in pivots([b for b in closed if b.is_valid() and not b.partial and not b.sampled])
                if not any(
                    (float(b.high) > p["price"] if p["kind"] == "high" else float(b.low) < p["price"])
                    for b in closed
                    if b.bar_time.isoformat() >= p["confirmed_at"]
                )
            ]
        cache[symbol] = (signature, result)
        state = process(symbol, result, quote, now)
        state["relative_strength"] = relative_strength(symbol, bars, benchmark, now)
        return result, state

    async def tick(symbol):
        try:
            quote = await repository.get_quote(symbol)
            # Copy on the event loop with no intervening await; worker gets immutable ownership.
            bars, benchmark = deepcopy(list(bars_by_symbol.get(symbol, ()))), deepcopy(
                list(bars_by_symbol.get("QQQ.US", ()))
            )
            now = utc_now()
            result, state = await asyncio.get_running_loop().run_in_executor(
                pool, compute, symbol, bars, benchmark, quote, now
            )
            ttl = cache_ttl("US", market_trading_date(now, "US"), now)
            if result:
                await repository.redis.set(result_key(symbol), json.dumps(result, allow_nan=False), ex=ttl)
            await repository.redis.set(f"rt:intraday-simulation:{symbol}", json.dumps(state, allow_nan=False), ex=ttl)
        except Exception:
            logger.exception("日内模拟计算失败: %s", symbol)

    try:
        while not stop_event.is_set():
            for symbol in SYMBOLS:
                if symbol not in pending or pending[symbol].done():
                    pending[symbol] = asyncio.create_task(tick(symbol))
            await asyncio.sleep(5)
    finally:
        await asyncio.gather(*pending.values(), return_exceptions=True)
        pool.shutdown(wait=True)

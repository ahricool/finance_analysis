"""Bounded worker scheduling. Async Redis remains exclusively on its owning loop."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import logging

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.intraday_simulation import (
    open_retired_symbols,
    process as _store_process,
    process_with_events,
)
from finance_analysis.intraday_options.config import SYMBOLS
from finance_analysis.intraday_options.notification import is_trade_event, notify_trade_events
from finance_analysis.intraday_options.scoring import calculate, closed_session_bars
from finance_analysis.intraday_options.simulation import CONFIG
from finance_analysis.intraday_options.structure import execution_context
from finance_analysis.market_stream.session import cache_ttl
from finance_analysis.market_stream.config import market_trading_date

logger = logging.getLogger(__name__)
process = _store_process


def _run_process(symbol, result, quote, now):
    if process is _store_process:
        return process_with_events(symbol, result, quote, now)
    return process(symbol, result, quote, now), []


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


def _peer_open_and_latest_bars(raw_bars, opening, now):
    """Copy only opening-minute and recent-tail versions per peer to keep event-loop snapshots light."""
    if not raw_bars:
        return []
    tail_floor = max(opening, now - timedelta(minutes=5))
    return [deepcopy(b) for b in raw_bars if b.bar_time == opening or b.bar_time >= tail_floor]


async def run(repository, bars_by_symbol, stop_event):
    from finance_analysis.intraday_options.runtime import result_key
    from finance_analysis.market_stream.session import session_bounds

    pool = ThreadPoolExecutor(max_workers=CONFIG.workers, thread_name_prefix="intraday-simulation")
    notify_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="intraday-notify")
    notify_tasks = set()
    pending = {}
    cache = {}
    retiring = None

    def compute(symbol, bars, benchmark, spy_bars, peer_bars, quote, now):
        now = utc_now()  # Queue wait must not make an old quote look fresh.
        if symbol not in SYMBOLS:
            state, events = _run_process(symbol, None, quote, now)
            return None, state, [e for e in events if is_trade_event(e)]
        closed = closed_session_bars(symbol, bars, now)
        spy_closed = closed_session_bars("SPY.US", spy_bars, now)
        peer_closed = {
            peer: closed_session_bars(peer, p_bars, now)
            for peer, p_bars in peer_bars.items()
        }
        # All relevant OHLCV/validity revisions invalidate shape cache.
        signature = tuple(
            (b.bar_time, b.received_at, b.open, b.high, b.low, b.close, b.volume, b.partial, b.sampled)
            for b in closed
        )
        spy_signature = tuple(
            (b.bar_time, b.received_at, b.open, b.high, b.low, b.close, b.volume, b.partial, b.sampled)
            for b in spy_closed
        )
        peer_signature = tuple(
            (
                peer,
                tuple(
                    (b.bar_time, b.received_at, b.open, b.close, b.is_valid(), b.partial, b.sampled)
                    for b in p_closed
                ),
            )
            for peer, p_closed in sorted(peer_closed.items())
        )
        prior = cache.get(symbol)
        base_result = (
            prior[1]
            if prior and prior[0] == signature
            else calculate(symbol, closed, now) if closed else None
        )
        if base_result is not None:
            if prior and prior[0] == signature and prior[2] == spy_signature and prior[3] == peer_signature:
                result = prior[4]
            else:
                result = {**base_result, **execution_context(closed, spy_closed, peer_bars=peer_closed)}
        else:
            result = None
        cache[symbol] = (signature, base_result, spy_signature, peer_signature, result)
        state, events = _run_process(symbol, result, quote, now)
        state["relative_strength"] = relative_strength(symbol, bars, benchmark, now)
        return result, state, [e for e in events if is_trade_event(e)]

    async def dispatch_notifications(batch, sym):
        try:
            await asyncio.get_running_loop().run_in_executor(notify_pool, notify_trade_events, batch)
        except Exception:
            logger.exception("日内模拟交易通知发送失败: %s", sym)

    async def tick(symbol):
        try:
            quote = await repository.get_quote(symbol)
            now = utc_now()
            bounds = session_bounds("US", market_trading_date(now, "US"))
            opening = bounds[0] if bounds else None
            # Copy on the event loop with no intervening await; worker gets immutable ownership.
            bars = deepcopy(list(bars_by_symbol.get(symbol, ())))
            benchmark = deepcopy(list(bars_by_symbol.get("QQQ.US", ())))
            spy_bars = bars if symbol == "SPY.US" else deepcopy(list(bars_by_symbol.get("SPY.US", ())))
            peer_bars = (
                {
                    peer: (
                        bars
                        if peer == symbol
                        else _peer_open_and_latest_bars(bars_by_symbol.get(peer, ()), opening, now)
                    )
                    for peer in SYMBOLS
                }
                if opening is not None
                else {}
            )
            result, state, trade_events = await asyncio.get_running_loop().run_in_executor(
                pool, compute, symbol, bars, benchmark, spy_bars, peer_bars, quote, now
            )
            if trade_events:
                task = asyncio.create_task(dispatch_notifications(trade_events, symbol))
                notify_tasks.add(task)
                task.add_done_callback(notify_tasks.discard)
            ttl = cache_ttl("US", market_trading_date(now, "US"), now)
            if symbol not in SYMBOLS and not state.get("position"):
                retiring.discard(symbol)
            if result:
                await repository.redis.set(result_key(symbol), json.dumps(result, allow_nan=False), ex=ttl)
            await repository.redis.set(f"rt:intraday-simulation:{symbol}", json.dumps(state, allow_nan=False), ex=ttl)
        except Exception:
            logger.exception("日内模拟计算失败: %s", symbol)

    try:
        while not stop_event.is_set():
            if retiring is None:
                try:
                    retiring = await asyncio.to_thread(open_retired_symbols)
                except Exception:
                    logger.exception("读取移出观察池的未平仓模拟交易失败")
            for symbol in (*SYMBOLS, *(retiring or ())):
                if symbol not in pending or pending[symbol].done():
                    pending[symbol] = asyncio.create_task(tick(symbol))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            await asyncio.gather(*pending.values(), return_exceptions=True)
            if notify_tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*list(notify_tasks), return_exceptions=True), timeout=5)
                except asyncio.TimeoutError:
                    logger.warning("日内模拟交易通知关闭等待超时，跳过未完成推送")
        finally:
            pool.shutdown(wait=True)
            notify_pool.shutdown(wait=False, cancel_futures=True)

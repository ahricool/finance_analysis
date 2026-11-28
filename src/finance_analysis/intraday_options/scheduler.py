"""Bounded worker scheduling. Async Redis remains exclusively on its owning loop."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, wait as wait_futures
from copy import deepcopy
from datetime import datetime, timedelta
import json
import logging
import threading
import time

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.intraday_simulation import (
    load_daily_context,
    load_universe_symbols,
    open_retired_symbols,
    process as _store_process,
    process_with_events,
)
from finance_analysis.intraday_options.config import BENCHMARK_SYMBOL_SET, SYMBOLS as _DEFAULT_SYMBOLS
from finance_analysis.intraday_options.opportunity_alert import alert_candidates, alert_opportunity
from finance_analysis.intraday_options.notification import is_trade_event, notify_trade_events
from finance_analysis.intraday_options.scoring import calculate, closed_session_bars, rolling_bars
from finance_analysis.intraday_options.simulation import CONFIG
from finance_analysis.intraday_options.structure import execution_context
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import cache_ttl

logger = logging.getLogger(__name__)
SYMBOLS = _DEFAULT_SYMBOLS
process = _store_process
_DAILY_CONTEXT_RETRY_SECONDS = 30.0


def _active_symbols() -> tuple[str, ...]:
    """Resolve active intraday universe from DB (with fallback), preserving test monkeypatches on SYMBOLS."""
    if SYMBOLS is not _DEFAULT_SYMBOLS:
        return tuple(SYMBOLS)
    return load_universe_symbols()


def _run_process(symbol, result, quote, now):
    if process is _store_process:
        return process_with_events(symbol, result, quote, now)
    return process(symbol, result, quote, now), []


def relative_strength(symbol, bars, benchmark, now):
    result = []
    left = {
        b.bar_time: b
        for b in rolling_bars(symbol, bars, now)
        if b.is_valid() and not b.partial and not b.sampled
    }
    right = {
        b.bar_time: b
        for b in rolling_bars("QQQ.US", benchmark, now)
        if b.is_valid() and not b.partial and not b.sampled
    }
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    for minutes in (5, 15, 30):
        times = [end - timedelta(minutes=i) for i in range(minutes)]
        available = 0
        for stamp in times:
            if stamp not in left or stamp not in right:
                break
            available += 1
        valid = symbol != "QQQ.US" and available > 0
        start = times[available - 1] if available else times[-1]
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
                minutes=minutes, available_minutes=available,
                value=value,
                start=start.isoformat(),
                end=(end + timedelta(minutes=1)).isoformat(),
                reason=(
                    ("同时间区间收益差，百分点" if available == minutes else f"仅覆盖{available}/{minutes}分钟，参考值")
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


def _build_round_peer_snapshot(bars_by_symbol, active_symbols, opening, now):
    """Build one shared, read-only peer-closed snapshot + cache signature per 5s round (O(N), excludes benchmarks)."""
    if opening is None:
        return {}, ()
    peer_closed = {}
    for peer in active_symbols:
        if peer in BENCHMARK_SYMBOL_SET:
            continue
        raw = _peer_open_and_latest_bars(bars_by_symbol.get(peer, ()), opening, now)
        peer_closed[peer] = tuple(closed_session_bars(peer, raw, now))
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
    return peer_closed, peer_signature


async def run(repository, bars_by_symbol, stop_event, *, bar_source=None):
    from finance_analysis.intraday_options.runtime import result_key
    from finance_analysis.market_stream.session import session_bounds

    pool = ThreadPoolExecutor(max_workers=CONFIG.workers, thread_name_prefix="intraday-simulation")
    notify_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="intraday-notify")
    notify_futures = set()
    notify_lock = threading.Lock()
    pending = {}
    cache = {}
    retiring = None
    last_active_symbols: tuple[str, ...] = ()
    daily_ctx_day = None
    daily_ctx_symbols: tuple[str, ...] = ()
    daily_ctx_map: dict[str, dict] = {}
    daily_ctx_retry_after = 0.0

    def submit_notifications(events, sym):
        trade_events = [deepcopy(e) for e in events if is_trade_event(e)]
        if not trade_events:
            return
        try:
            future = notify_pool.submit(notify_trade_events, trade_events)
        except Exception:
            logger.exception("提交日内模拟交易通知失败: %s", sym)
            return

        def finish(done_future):
            with notify_lock:
                notify_futures.discard(done_future)
            if done_future.cancelled():
                return
            try:
                done_future.result()
            except Exception:
                logger.exception("日内模拟交易通知发送失败: %s", sym)

        with notify_lock:
            notify_futures.add(future)
        future.add_done_callback(finish)

    def compute(
        symbol,
        active_set,
        bars,
        benchmark,
        spy_bars,
        round_peer_closed,
        round_peer_signature,
        symbol_daily_ctx,
        symbol_daily_ctx_day,
        quote,
        now,
    ):
        now = utc_now()  # Queue wait must not make an old quote look fresh.
        if symbol not in active_set:
            state, events = _run_process(symbol, None, quote, now)
            submit_notifications(events, symbol)
            return None, state
        closed = closed_session_bars(symbol, bars, now)
        rolling = rolling_bars(symbol, bars, now)
        spy_closed = closed_session_bars("SPY.US", spy_bars, now)
        # All relevant OHLCV/validity revisions invalidate shape cache.
        signature = tuple(
            (b.indicator_input(), b.received_at)
            for b in rolling
        )
        spy_signature = tuple(
            (b.indicator_input(), b.received_at)
            for b in spy_closed
        )
        day = market_trading_date(closed[-1].bar_time, "US") if closed else market_trading_date(now, "US")
        effective_daily_ctx = symbol_daily_ctx if (symbol_daily_ctx and symbol_daily_ctx_day == day) else {}
        live_pre_close = (
            quote.pre_close
            if quote is not None and quote.trading_date == day and quote.pre_close is not None and quote.pre_close > 0
            else None
        )
        execution_signature = tuple((b.indicator_input(), b.received_at) for b in closed)
        daily_signature = (
            execution_signature,
            str(live_pre_close) if live_pre_close is not None else None,
            effective_daily_ctx.get("prev_close") if effective_daily_ctx else None,
            effective_daily_ctx.get("daily_atr_pct") if effective_daily_ctx else None,
            effective_daily_ctx.get("as_of") if effective_daily_ctx else None,
        )
        prior = cache.get(symbol)
        base_result = (
            prior[1]
            if prior and prior[0] == signature
            else calculate(symbol, rolling, now) if rolling else None
        )
        if base_result is not None:
            if (
                prior
                and prior[0] == signature
                and prior[2] == spy_signature
                and prior[3] == round_peer_signature
                and prior[4] == daily_signature
            ):
                result = prior[5]
            else:
                if symbol in BENCHMARK_SYMBOL_SET:
                    peer_for_symbol = round_peer_closed
                else:
                    peer_for_symbol = {**round_peer_closed, symbol: closed}
                result = {
                    **base_result,
                    **execution_context(
                        closed,
                        spy_closed,
                        peer_bars=peer_for_symbol,
                        daily_context=effective_daily_ctx,
                        pre_close=live_pre_close,
                    ),
                }
        else:
            result = None
        cache[symbol] = (signature, base_result, spy_signature, round_peer_signature, daily_signature, result)
        try:
            state, events = _run_process(symbol, result, quote, now)
        except Exception:
            logger.exception("日内模拟写入失败，保留上次模拟状态: %s", symbol)
            return result, None
        submit_notifications(events, symbol)
        state["relative_strength"] = relative_strength(symbol, bars, benchmark, now)
        return result, state

    async def tick(
        symbol,
        active_set,
        round_qqq_bars,
        round_spy_bars,
        round_peer_closed,
        round_peer_signature,
        symbol_daily_ctx,
        symbol_daily_ctx_day,
        round_symbol_bars,
        round_quotes,
    ):
        try:
            quote = await repository.get_quote(symbol) if round_quotes is None else round_quotes.get(symbol)
            now = utc_now()
            # Worker owns an immutable copy of this round's input.
            bars = round_symbol_bars if bar_source is not None else deepcopy(list(round_symbol_bars))
            spy_bars = bars if symbol == "SPY.US" else round_spy_bars
            benchmark = bars if symbol == "QQQ.US" else round_qqq_bars
            result, state = await asyncio.get_running_loop().run_in_executor(
                pool,
                compute,
                symbol,
                active_set,
                bars,
                benchmark,
                spy_bars,
                round_peer_closed,
                round_peer_signature,
                symbol_daily_ctx,
                symbol_daily_ctx_day,
                quote,
                now,
            )
            ttl = cache_ttl("US", market_trading_date(now, "US"), now)
            if state is not None and symbol not in active_set and not state.get("position") and retiring is not None:
                retiring.discard(symbol)
            if result:
                await repository.redis.set(result_key(symbol), json.dumps(result, allow_nan=False), ex=ttl)
            if state is not None:
                await repository.redis.set(f"rt:intraday-simulation:{symbol}", json.dumps(state, allow_nan=False), ex=ttl)
            if result and quote and quote.timestamp_kind != "received" and quote.last_price and quote.last_price > 0:
                at = utc_now()
                if quote.received_at and 0 <= (at - quote.received_at).total_seconds() <= 30:
                    for candidate in alert_candidates(result.get("opportunities")):
                        await alert_opportunity(repository.redis, symbol, candidate, datetime.fromisoformat(result["as_of"]),
                                                quote.event_time, at)
        except Exception:
            logger.exception("日内模拟计算失败: %s", symbol)

    try:
        while not stop_event.is_set():
            active_symbols = await asyncio.to_thread(_active_symbols)
            active_set = frozenset(active_symbols)
            if retiring is None or active_symbols != last_active_symbols:
                try:
                    retiring = await asyncio.to_thread(open_retired_symbols)
                    last_active_symbols = active_symbols
                except Exception:
                    logger.exception("读取移出观察池的未平仓模拟交易失败")
            now_round = utc_now()
            today = market_trading_date(now_round, "US")
            mono = time.monotonic()
            if daily_ctx_day is not None and daily_ctx_day != today:
                # Immediately purge yesterday's daily context on day rollover so stale prev_close never leaks.
                daily_ctx_map = {}
                daily_ctx_day = None
                daily_ctx_symbols = ()
                daily_ctx_retry_after = 0.0
            if (daily_ctx_day != today or daily_ctx_symbols != active_symbols) and mono >= daily_ctx_retry_after:
                try:
                    daily_ctx_map = await asyncio.to_thread(load_daily_context, active_symbols, today)
                    daily_ctx_day = today
                    daily_ctx_symbols = active_symbols
                    daily_ctx_retry_after = 0.0
                except Exception:
                    logger.warning("批量读取日线 ATR/昨收上下文失败，稍后重试", exc_info=True)
                    daily_ctx_retry_after = mono + _DAILY_CONTEXT_RETRY_SECONDS
            symbols = tuple(dict.fromkeys((*active_symbols, *(retiring or ()))))
            round_bars = bars_by_symbol
            round_quotes = None
            if bar_source is not None:
                try:
                    round_bars = await bar_source.refresh((*symbols, *BENCHMARK_SYMBOL_SET))
                except Exception:
                    # Missing history blocks new entries; a fresh quote may still
                    # manage a previously persisted position.
                    logger.exception("Trader 读取闭合分钟行情失败")
                    round_bars = {}
                try:
                    round_quotes = await repository.get_quotes(symbols)
                except Exception:
                    logger.exception("Trader 读取实时报价失败")
                    round_quotes = {}
            # Build peer snapshots once; every symbol sees the same round input.
            bounds = session_bounds("US", today)
            opening = bounds[0] if bounds else None
            round_qqq_bars = tuple(deepcopy(list(round_bars.get("QQQ.US", ()))))
            round_spy_bars = tuple(deepcopy(list(round_bars.get("SPY.US", ()))))
            round_peer_closed, round_peer_signature = _build_round_peer_snapshot(
                round_bars, active_symbols, opening, now_round
            )
            for symbol in symbols:
                if symbol not in pending or pending[symbol].done():
                    pending[symbol] = asyncio.create_task(
                        tick(
                            symbol,
                            active_set,
                            round_qqq_bars,
                            round_spy_bars,
                            round_peer_closed,
                            round_peer_signature,
                            daily_ctx_map.get(symbol, {}),
                            daily_ctx_day,
                            round_bars.get(symbol, ()),
                            round_quotes,
                        )
                    )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            await asyncio.gather(*pending.values(), return_exceptions=True)
        finally:
            pool.shutdown(wait=True)
            with notify_lock:
                remaining = list(notify_futures)
            if remaining:
                _, not_done = wait_futures(remaining, timeout=5)
                if not_done:
                    logger.warning("日内模拟交易通知关闭等待超时，跳过 %s 条未完成推送", len(not_done))
            notify_pool.shutdown(wait=False, cancel_futures=True)

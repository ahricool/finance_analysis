"""Standalone multi-market Longbridge streamer orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.providers.longbridge.normalizer import MarketEvent, event_to_candle
from finance_analysis.integrations.market_data.providers.longbridge.streaming import LongbridgeStreamingClient
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState, TrendState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import (
    MarketStreamConfig,
    completed_regular_minutes,
    is_regular_session_minute,
    is_regular_trade_session,
    latest_completed_bar_time,
    market_spec,
    market_trading_date,
)
from finance_analysis.market_stream.leader_lock import LeaderLock
from finance_analysis.market_stream.subscription_manager import (
    SubscriptionManager,
    WarmupFinalizer,
    WarmupTaskKey,
)
from finance_analysis.market_stream.symbol_state import (
    ConnectionStatus,
    SubscriptionTarget,
    SymbolRuntimeState,
    SymbolStatus,
)
from finance_analysis.market_stream.trend import calculate_ma_trend
from finance_analysis.market_stream.warmup import LongbridgeHistoryLoader, merge_warmup_bars
from finance_analysis.market_stream.watchlist_monitor import WatchListMonitor
from finance_analysis.stocks.markets import MarketType

logger = logging.getLogger(__name__)
QUOTE_REFERENCE_RETRY_SECONDS = 60


@dataclass(slots=True)
class WarmupResult:
    symbol: str
    market_type: MarketType
    cached: list[CandleState]
    historical: list[CandleState]
    elapsed_seconds: float


class MarketStreamService:
    def __init__(
        self,
        *,
        config: MarketStreamConfig | None = None,
        repository: RealtimeStateRepository | None = None,
        watchlist_monitor: WatchListMonitor | None = None,
        client_factory: Any = LongbridgeStreamingClient,
        history_loader: Any | None = None,
    ) -> None:
        self.config = config or MarketStreamConfig.from_env()
        self.repository = repository or RealtimeStateRepository.from_url(
            self.config.redis_url,
            bar_limit=self.config.bar_limit,
            removed_ttl_seconds=self.config.removed_symbol_cache_ttl_seconds,
        )
        self.watchlist_monitor = watchlist_monitor or WatchListMonitor()
        self.history_loader = history_loader or LongbridgeHistoryLoader()
        self.event_queue: asyncio.Queue[MarketEvent] = asyncio.Queue(maxsize=self.config.event_queue_size)
        self.quotes: dict[str, QuoteState] = {}
        self.bars_1m: dict[str, deque[CandleState]] = {}
        self.current_candles: dict[str, CandleState] = {}
        self.warming_buffers: dict[
            WarmupTaskKey,
            dict[tuple[datetime, str], CandleState],
        ] = {}
        self.symbol_locks: dict[str, asyncio.Lock] = {}
        self.pending_quotes: dict[str, QuoteState] = {}
        self.pending_candles: dict[str, CandleState] = {}
        self.pending_bars: dict[str, dict[tuple[datetime, str], CandleState]] = {}
        self.pending_trends: dict[str, TrendState] = {}
        self.quote_reference_dates: dict[str, date] = {}
        self.quote_reference_attempts: dict[str, datetime] = {}
        self.last_event_at: datetime | None = None
        self.redis_degraded = False
        self.stop_event = asyncio.Event()
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.warmup_semaphore = asyncio.Semaphore(self.config.warmup_concurrency)
        self.manager = SubscriptionManager(
            client_factory=client_factory,
            event_sink=self._enqueue_event,
            warmup_loader=self._load_warmup,
            warmup_apply=self._apply_warmup,
            state_callback=self._write_symbol_state,
            removal_callback=self._remove_symbol_state,
            desired_loader=self._reload_desired_targets,
            connection_cleanup_callback=self._cleanup_connection_buffers,
            minimum_history_bars=self.config.minimum_history_bars,
        )
        self.leader_lock = LeaderLock(
            self.repository.redis,
            ttl_seconds=self.config.leader_lock_ttl_seconds,
        )

    def _symbol_lock(self, symbol: str) -> asyncio.Lock:
        return self.symbol_locks.setdefault(symbol, asyncio.Lock())

    def request_stop(self) -> None:
        self.stop_event.set()

    async def run(self) -> bool:
        logger.info("market streamer 启动: instance_id=%s", self.instance_id)
        if not await self.leader_lock.acquire():
            logger.error("Leader Lock 获取失败，已有 streamer 实例运行")
            await self.repository.close()
            return False
        logger.info("Leader Lock 获取成功")

        tasks = [
            asyncio.create_task(self._renew_leader_lock(), name="market-stream-lock"),
            asyncio.create_task(self._consume_events(), name="market-stream-events"),
            asyncio.create_task(self._flush_redis(), name="market-stream-redis"),
            asyncio.create_task(self._heartbeat(), name="market-stream-heartbeat"),
            asyncio.create_task(self._refresh_quote_references(), name="market-stream-quote-references"),
        ]
        try:
            snapshot = await self.watchlist_monitor.poll()
            self.manager.desired_targets = snapshot.targets
            tasks.extend(
                [
                    asyncio.create_task(self.manager.start(), name="market-stream-connect"),
                    asyncio.create_task(self._poll_watchlist(), name="market-stream-watchlist"),
                    asyncio.create_task(self._check_connection(), name="market-stream-health"),
                ]
            )
            await self.stop_event.wait()
        finally:
            self.stop_event.set()
            await self.manager.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await self.leader_lock.release()
            finally:
                await self.repository.close()
            logger.info("market streamer 已停止")
        return True

    def _enqueue_event(self, event: MarketEvent) -> None:
        try:
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("行情事件队列已满，丢弃事件: type=%s symbol=%s", event.event_type, event.symbol)

    async def _poll_watchlist(self) -> None:
        while not self.stop_event.is_set():
            try:
                snapshot = await self.watchlist_monitor.poll()
                await self.manager.reconcile(snapshot.targets)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("读取或同步 WatchList 失败: %s", exc)
            await asyncio.sleep(self.config.watchlist_poll_seconds)

    async def _reload_desired_targets(self) -> dict[str, SubscriptionTarget]:
        return (await self.watchlist_monitor.poll()).targets

    async def _consume_events(self) -> None:
        while not self.stop_event.is_set():
            event = await self.event_queue.get()
            try:
                await self._handle_event(event)
            except Exception as exc:
                logger.warning("行情事件处理失败: symbol=%s error=%s", event.symbol, exc)
            finally:
                self.event_queue.task_done()

    async def _handle_event(self, event: MarketEvent) -> None:
        if event.connection_generation != self.manager.connection_generation:
            return
        state = self.manager.symbol_states.get(event.symbol)
        if state is None or event.symbol not in self.manager.desired_targets:
            return
        if state.status in {SymbolStatus.REMOVING, SymbolStatus.INACTIVE, SymbolStatus.PENDING}:
            return
        self.last_event_at = event.received_at
        if event.event_type in {"quote", "quote_snapshot", "quote_reference"}:
            quote = self.quotes.setdefault(event.symbol, QuoteState(symbol=event.symbol))
            event_time = (
                quote.event_time if event.event_type == "quote_reference" and quote.event_time else event.event_time
            )
            received_at = (
                quote.received_at if event.event_type == "quote_reference" and quote.received_at else event.received_at
            )
            if quote.merge(event.payload, event_time=event_time, received_at=received_at):
                if event.event_type == "quote":
                    state.last_quote_at = event.received_at
                if event.event_type == "quote_reference" and event.payload.get("pre_close") is not None:
                    self.quote_reference_dates[event.symbol] = market_trading_date(utc_now(), state.market_type)
                self.pending_quotes[event.symbol] = quote
        elif event.event_type == "candle_1m":
            candle = event_to_candle(event)
            if candle.is_valid():
                await self._handle_candle(candle, event.connection_generation)
        logger.debug("行情事件: type=%s symbol=%s", event.event_type, event.symbol)

    async def _handle_candle(self, candle: CandleState, connection_generation: int) -> None:
        state: SymbolRuntimeState | None = None
        accepted = False
        count = 0
        async with self._symbol_lock(candle.symbol):
            if connection_generation != self.manager.connection_generation:
                return
            state = self.manager.symbol_states.get(candle.symbol)
            if state is None or candle.symbol not in self.manager.desired_targets:
                return
            if state.status in {SymbolStatus.REMOVING, SymbolStatus.INACTIVE, SymbolStatus.PENDING}:
                return
            state.last_candle_at = candle.received_at
            if state.status == SymbolStatus.WARMING:
                key = WarmupTaskKey(candle.symbol, state.generation, connection_generation)
                buffer = self.warming_buffers.setdefault(key, {})
                existing = buffer.get(candle.identity)
                if existing is None or candle.received_at >= existing.received_at:
                    buffer[candle.identity] = candle
                return
            accepted, count = self._update_live_candle_memory(candle, state)

        if not accepted or state is None:
            return
        if candle.confirmed:
            try:
                await self.repository.upsert_bars(candle.symbol, [candle])
                self._discard_pending_bars(candle.symbol, [candle])
                self.redis_degraded = False
            except Exception as exc:
                self._queue_pending_bars(candle.symbol, [candle])
                self.redis_degraded = True
                logger.warning("Redis K 线写入失败: symbol=%s error=%s", candle.symbol, exc)
            if is_regular_session_minute(candle.bar_time, state.market_type) and is_regular_trade_session(
                candle.trade_session
            ):
                await self._update_trend_state(
                    candle.symbol,
                    state.market_type,
                    as_of=max(candle.received_at, candle.bar_time + timedelta(minutes=1)),
                )
        if (
            state.status in {SymbolStatus.INSUFFICIENT_HISTORY, SymbolStatus.ERROR}
            and count >= self.config.minimum_history_bars
        ):
            await self.manager.bars_updated(candle.symbol, count, symbol_generation=state.generation)

    def _update_live_candle_memory(
        self,
        candle: CandleState,
        state: SymbolRuntimeState,
    ) -> tuple[bool, int]:
        candle_date = market_trading_date(candle.bar_time, state.market_type)
        if state.trading_date is not None and candle_date < state.trading_date:
            return False, len(self.bars_1m.get(candle.symbol, ()))
        if state.trading_date is not None and candle_date > state.trading_date:
            self.bars_1m.pop(candle.symbol, None)
            self.current_candles.pop(candle.symbol, None)
        state.trading_date = candle_date

        bars = self.bars_1m.setdefault(candle.symbol, deque(maxlen=self.config.bar_limit))
        existing = {bar.identity: bar for bar in bars}
        previous = existing.get(candle.identity)
        if previous is not None and (
            previous.symbol,
            previous.open,
            previous.high,
            previous.low,
            previous.close,
            previous.volume,
            previous.turnover,
            previous.confirmed,
        ) == (
            candle.symbol,
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
            candle.turnover,
            candle.confirmed,
        ):
            return False, len(bars)
        if previous is not None and candle.received_at < previous.received_at:
            return False, len(bars)
        existing[candle.identity] = candle
        ordered = sorted(existing.values(), key=lambda item: (item.bar_time, item.trade_session or ""))
        updated = deque(ordered[-self.config.bar_limit :], maxlen=self.config.bar_limit)
        self.bars_1m[candle.symbol] = updated
        current = updated[-1]
        self.current_candles[candle.symbol] = current
        self.pending_candles[candle.symbol] = current
        return True, len(updated)

    async def _update_trend_state(
        self,
        symbol: str,
        market_type: MarketType,
        *,
        as_of: datetime,
    ) -> None:
        try:
            trend = calculate_ma_trend(
                list(self.bars_1m.get(symbol, ())),
                market_type=market_type,
                as_of=as_of,
            )
        except Exception as exc:
            logger.warning("1 分钟趋势计算失败: symbol=%s error=%s", symbol, exc, exc_info=True)
            return
        try:
            await self.repository.write_trend_state(trend)
            self.pending_trends.pop(symbol, None)
        except Exception as exc:
            self.pending_trends[symbol] = trend
            self.redis_degraded = True
            logger.warning("Redis 趋势写入失败: symbol=%s error=%s", symbol, exc)

    async def _load_warmup(
        self,
        symbol: str,
        market_type: MarketType,
        symbol_generation: int,
        connection_generation: int,
    ) -> WarmupResult:
        started = time.monotonic()
        logger.info(
            "warmup 开始: %s market=%s symbol_generation=%s connection_generation=%s",
            symbol,
            market_type,
            symbol_generation,
            connection_generation,
        )
        async with self.warmup_semaphore:
            cached: list[CandleState] = []
            try:
                cached = await self.repository.get_recent_bars(symbol, self.config.bar_limit)
            except Exception as exc:
                self.redis_degraded = True
                logger.warning("Redis warmup 恢复失败: symbol=%s error=%s", symbol, exc)
            historical: list[CandleState] = []
            if not self._cache_has_current_session(cached, market_type):
                historical = await self.history_loader.fetch(symbol, market_type, self.config.bar_limit)
            return WarmupResult(
                symbol,
                market_type,
                cached,
                historical,
                time.monotonic() - started,
            )

    def _cache_has_current_session(
        self,
        bars: list[CandleState],
        market_type: MarketType,
        *,
        now: datetime | None = None,
    ) -> bool:
        now = now or utc_now()
        expected = latest_completed_bar_time(now, market_type)
        if not bars or expected is None:
            return False
        current_date = market_trading_date(now, market_type)
        completed = [
            bar
            for bar in bars
            if market_trading_date(bar.bar_time, market_type) == current_date and bar.bar_time <= expected
        ]
        if not completed:
            return False
        newest = max(bar.bar_time for bar in completed)
        gap = expected - newest
        if gap.total_seconds() < 0 or gap > market_spec(market_type).cache_gap_tolerance:
            return False
        required = min(
            self.config.minimum_history_bars,
            completed_regular_minutes(now, market_type),
        )
        return required > 0 and len(completed) >= required

    async def _apply_warmup(
        self,
        state: SymbolRuntimeState,
        connection_generation: int,
        result: WarmupResult | None,
        error: Exception | None,
        finalize: WarmupFinalizer,
    ) -> bool:
        key = WarmupTaskKey(state.symbol, state.generation, connection_generation)
        buffered_count = 0
        bars: list[CandleState] = []
        trading_date: date | None = None
        async with self._symbol_lock(state.symbol):
            current = self.manager.symbol_states.get(state.symbol)
            target = self.manager.desired_targets.get(state.symbol)
            if (
                current is not state
                or target is None
                or target.market_type != state.market_type
                or connection_generation != self.manager.connection_generation
                or state.status != SymbolStatus.WARMING
            ):
                return False
            buffered = list(self.warming_buffers.pop(key, {}).values())
            buffered_count = len(buffered)
            base_bars = [] if result is None else result.cached + result.historical
            bars = merge_warmup_bars(base_bars, buffered, limit=self.config.bar_limit)
            if bars:
                trading_date = max(market_trading_date(bar.bar_time, state.market_type) for bar in bars)
                bars = [bar for bar in bars if market_trading_date(bar.bar_time, state.market_type) == trading_date]
            else:
                trading_date = market_trading_date(utc_now(), state.market_type)
            self.bars_1m[state.symbol] = deque(bars, maxlen=self.config.bar_limit)
            if bars:
                self.current_candles[state.symbol] = bars[-1]
                self.pending_candles[state.symbol] = bars[-1]
            finalize(len(bars), error, trading_date)

        try:
            await self.repository.upsert_bars(state.symbol, bars)
            if bars:
                await self.repository.write_current_candle(bars[-1])
            self._discard_pending_bars(state.symbol, bars)
            self.redis_degraded = False
        except Exception as exc:
            self._queue_pending_bars(state.symbol, bars)
            self.redis_degraded = True
            logger.warning("Redis warmup 写入失败: symbol=%s error=%s", state.symbol, exc)
        if bars:
            await self._update_trend_state(
                state.symbol,
                state.market_type,
                as_of=bars[-1].bar_time + timedelta(minutes=1),
            )
        logger.info(
            "warmup 数据合并: %s cache=%s history=%s realtime=%s final=%s elapsed=%.3fs",
            state.symbol,
            len(result.cached) if result is not None else 0,
            len(result.historical) if result is not None else 0,
            buffered_count,
            len(bars),
            result.elapsed_seconds if result is not None else 0.0,
        )
        return True

    async def _flush_redis(self) -> None:
        interval = self.config.redis_flush_interval_ms / 1000
        while not self.stop_event.is_set():
            await asyncio.sleep(interval)
            await self._flush_pending_redis()

    async def _flush_pending_redis(self) -> bool:
        quotes, candles, bars, trends = (
            self.pending_quotes,
            self.pending_candles,
            self.pending_bars,
            self.pending_trends,
        )
        self.pending_quotes, self.pending_candles, self.pending_bars, self.pending_trends = {}, {}, {}, {}
        if not quotes and not candles and not bars and not trends:
            return True
        try:
            await self.repository.write_batch(quotes, candles, trends)
            await self.repository.upsert_bars_batch({symbol: list(items.values()) for symbol, items in bars.items()})
            self.redis_degraded = False
            return True
        except Exception as exc:
            self.redis_degraded = True
            for symbol, quote in quotes.items():
                self.pending_quotes.setdefault(symbol, quote)
            for symbol, candle in candles.items():
                self.pending_candles.setdefault(symbol, candle)
            for symbol, items in bars.items():
                self._queue_pending_bars(symbol, items.values())
            self.pending_trends.update(trends)
            logger.warning("Redis 批量写入失败，稍后重试: %s", exc)
            return False

    def _queue_pending_bars(self, symbol: str, bars: Iterable[CandleState]) -> None:
        pending = self.pending_bars.setdefault(symbol, {})
        for bar in bars:
            existing = pending.get(bar.identity)
            if existing is None or (bar.confirmed, bar.received_at) >= (
                existing.confirmed,
                existing.received_at,
            ):
                pending[bar.identity] = bar
        if len(pending) > self.config.bar_limit:
            retained = sorted(pending.items(), key=lambda item: item[0])[-self.config.bar_limit :]
            self.pending_bars[symbol] = dict(retained)

    def _discard_pending_bars(self, symbol: str, bars: Iterable[CandleState]) -> None:
        pending = self.pending_bars.get(symbol)
        if not pending:
            return
        for bar in bars:
            pending.pop(bar.identity, None)
        if not pending:
            self.pending_bars.pop(symbol, None)

    async def _write_symbol_state(self, state: SymbolRuntimeState) -> None:
        try:
            await self.repository.write_subscription(
                state.symbol,
                state.redis_mapping(utc_now()),
                ttl_seconds=self.config.subscription_state_ttl_seconds,
            )
        except Exception:
            self.redis_degraded = True
            raise

    async def _remove_symbol_state(self, symbol: str) -> None:
        async with self._symbol_lock(symbol):
            self.quotes.pop(symbol, None)
            self.bars_1m.pop(symbol, None)
            self.current_candles.pop(symbol, None)
            for key in [key for key in self.warming_buffers if key.symbol == symbol]:
                self.warming_buffers.pop(key, None)
            self.pending_quotes.pop(symbol, None)
            self.pending_candles.pop(symbol, None)
            self.pending_bars.pop(symbol, None)
            self.pending_trends.pop(symbol, None)
            self.quote_reference_dates.pop(symbol, None)
            self.quote_reference_attempts.pop(symbol, None)
        try:
            await self.repository.expire_symbol_cache(
                symbol,
                ttl_seconds=self.config.removed_symbol_cache_ttl_seconds,
            )
        except Exception as exc:
            self.redis_degraded = True
            logger.warning("设置已删除标的缓存 TTL 失败: symbol=%s error=%s", symbol, exc)

    async def _cleanup_connection_buffers(self, connection_generation: int) -> None:
        # Quote sequence values are connection-scoped. Keep the merged fields
        # for partial pushes, but let the new connection establish a baseline.
        for symbol, quote in self.quotes.items():
            quote.sequence = None
            self.pending_quotes.pop(symbol, None)
        symbols = {key.symbol for key in self.warming_buffers if key.connection_generation <= connection_generation}
        for symbol in symbols:
            async with self._symbol_lock(symbol):
                for key in [
                    key
                    for key in self.warming_buffers
                    if key.symbol == symbol and key.connection_generation <= connection_generation
                ]:
                    self.warming_buffers.pop(key, None)

    async def _heartbeat(self) -> None:
        renewable_statuses = {
            SymbolStatus.PENDING,
            SymbolStatus.WARMING,
            SymbolStatus.ACTIVE,
            SymbolStatus.INSUFFICIENT_HISTORY,
            SymbolStatus.ERROR,
            SymbolStatus.REMOVING,
        }
        while not self.stop_event.is_set():
            status = ConnectionStatus.DEGRADED if self.redis_degraded else self.manager.connection_status
            try:
                await self.repository.write_heartbeat(
                    {
                        "instance_id": self.instance_id,
                        "status": status,
                        "connection_generation": self.manager.connection_generation,
                        "desired_symbols": ",".join(sorted(self.manager.desired_targets)),
                        "active_symbols": ",".join(sorted(self.manager.active_symbols)),
                        "warming_symbols": ",".join(sorted(self.manager.warming_symbols)),
                        "last_event_at": self.last_event_at,
                        "updated_at": utc_now(),
                    },
                    ttl_seconds=self.config.heartbeat_ttl_seconds,
                )
                renewable = [
                    state.symbol for state in self.manager.symbol_states.values() if state.status in renewable_statuses
                ]
                await self.repository.refresh_subscription_ttls(
                    renewable,
                    ttl_seconds=self.config.subscription_state_ttl_seconds,
                )
                self.redis_degraded = False
            except Exception as exc:
                self.redis_degraded = True
                logger.warning("streamer 心跳写入失败: %s", exc)
            await asyncio.sleep(self.config.heartbeat_seconds)

    async def _refresh_quote_references(self) -> None:
        interval = max(1, self.config.heartbeat_seconds)
        while not self.stop_event.is_set():
            await asyncio.sleep(interval)
            try:
                await self._refresh_quote_references_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("刷新跨日昨收价失败: %s", exc)

    async def _refresh_quote_references_once(self, *, now: datetime | None = None) -> set[str]:
        current = now or utc_now()
        dates: dict[str, date] = {}
        stale: set[str] = set()
        retry_after = timedelta(seconds=QUOTE_REFERENCE_RETRY_SECONDS)
        for state in self.manager.symbol_states.values():
            if not state.quote_subscribed or state.status in {
                SymbolStatus.INACTIVE,
                SymbolStatus.REMOVING,
            }:
                continue
            reference_date = market_trading_date(current, state.market_type)
            if (
                state.last_quote_at is None
                or market_trading_date(state.last_quote_at, state.market_type) != reference_date
            ):
                # Do not refresh merely because the local calendar rolled over.
                # The first push of the new market date proves that Longbridge
                # has started publishing that session's quote state.
                continue
            dates[state.symbol] = reference_date
            last_attempt = self.quote_reference_attempts.get(state.symbol)
            if self.quote_reference_dates.get(state.symbol) != reference_date and (
                last_attempt is None or current - last_attempt >= retry_after
            ):
                stale.add(state.symbol)
        if not stale:
            return set()
        for symbol in stale:
            self.quote_reference_attempts[symbol] = current
        refreshed = await self.manager.refresh_quotes(stale)
        for symbol in refreshed:
            if symbol in dates:
                self.quote_reference_dates[symbol] = dates[symbol]
        return refreshed

    async def _renew_leader_lock(self) -> None:
        interval = max(1, self.config.leader_lock_ttl_seconds // 3)
        while not self.stop_event.is_set():
            await asyncio.sleep(interval)
            try:
                if not await self.leader_lock.renew():
                    logger.error("Leader Lock 已丢失，停止 streamer")
                    self.request_stop()
                    return
            except Exception as exc:
                logger.error("Leader Lock 续租失败，停止 streamer: %s", exc)
                self.request_stop()
                return

    async def _check_connection(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(max(self.config.heartbeat_seconds, self.config.watchlist_poll_seconds))
            if self.manager.connection_status in {ConnectionStatus.READY, ConnectionStatus.DEGRADED}:
                try:
                    healthy = await self.manager.health_check()
                    if not healthy:
                        logger.info("长桥重连和 WatchList 重新订阅已完成")
                except Exception as exc:
                    logger.warning("连接健康检查失败: %s", exc)

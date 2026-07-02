"""Serialized multi-market subscription lifecycle and generation protection."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from finance_analysis.core.time import utc_now
from finance_analysis.market_stream.symbol_state import (
    ConnectionStatus,
    SubscriptionTarget,
    SymbolRuntimeState,
    SymbolStatus,
)
from finance_analysis.stocks.markets import MarketType

logger = logging.getLogger(__name__)

StateCallback = Callable[[SymbolRuntimeState], Awaitable[None]]
WarmupLoader = Callable[[str, MarketType, int, int], Awaitable[Any]]
WarmupFinalizer = Callable[[int, Exception | None, date | None], None]
WarmupApply = Callable[
    [SymbolRuntimeState, int, Any, Exception | None, WarmupFinalizer],
    Awaitable[bool],
]
RemovalCallback = Callable[[str], Awaitable[None]]
DesiredLoader = Callable[[], Awaitable[Mapping[str, SubscriptionTarget]]]
ConnectionCleanupCallback = Callable[[int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WarmupTaskKey:
    symbol: str
    symbol_generation: int
    connection_generation: int


@dataclass(slots=True)
class SubscriptionCommand:
    action: str
    payload: Any = None
    connection_generation: int | None = None
    symbol_generation: int | None = None
    future: asyncio.Future[Any] | None = None


class SubscriptionManager:
    """Own all streaming client calls and serialized symbol state transitions."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any],
        event_sink: Callable[[Any], None],
        warmup_loader: WarmupLoader,
        warmup_apply: WarmupApply,
        state_callback: StateCallback,
        removal_callback: RemovalCallback,
        desired_loader: DesiredLoader | None = None,
        connection_cleanup_callback: ConnectionCleanupCallback | None = None,
        minimum_history_bars: int = 15,
    ) -> None:
        self.client_factory = client_factory
        self.event_sink = event_sink
        self.warmup_loader = warmup_loader
        self.warmup_apply = warmup_apply
        self.state_callback = state_callback
        self.removal_callback = removal_callback
        self.desired_loader = desired_loader
        self.connection_cleanup_callback = connection_cleanup_callback
        self.minimum_history_bars = minimum_history_bars
        self.commands: asyncio.Queue[SubscriptionCommand] = asyncio.Queue()
        self.desired_targets: dict[str, SubscriptionTarget] = {}
        self.active_symbols: set[str] = set()
        self.warming_symbols: set[str] = set()
        self.removing_symbols: set[str] = set()
        self.symbol_states: dict[str, SymbolRuntimeState] = {}
        self.connection_generation = 0
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.client: Any | None = None
        self._worker: asyncio.Task[None] | None = None
        self._warmup_tasks: dict[WarmupTaskKey, asyncio.Task[None]] = {}
        self._stopping = False
        self._stop_signal = asyncio.Event()

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="market-stream-subscriptions")
        await self._request("connect")

    async def reconcile(
        self,
        desired_targets: Mapping[str, SubscriptionTarget],
        *,
        generation: int | None = None,
    ) -> None:
        await self._request("reconcile", dict(desired_targets), connection_generation=generation)

    async def health_check(self) -> bool:
        return bool(await self._request("health"))

    async def reconnect(self) -> None:
        await self._request("reconnect")

    async def refresh_quotes(self, symbols: set[str]) -> set[str]:
        return set(await self._request("refresh_quotes", set(symbols)))

    async def bars_updated(self, symbol: str, count: int, *, symbol_generation: int) -> None:
        await self._request("bars_updated", (symbol, count), symbol_generation=symbol_generation)

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._stopping = True
        self._stop_signal.set()
        try:
            await self._request("stop")
        finally:
            await self._worker
            self._worker = None

    async def _request(
        self,
        action: str,
        payload: Any = None,
        *,
        connection_generation: int | None = None,
        symbol_generation: int | None = None,
    ) -> Any:
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await self.commands.put(
            SubscriptionCommand(action, payload, connection_generation, symbol_generation, future)
        )
        return await future

    async def _run(self) -> None:
        while True:
            command = await self.commands.get()
            try:
                if (
                    command.connection_generation is not None
                    and command.connection_generation != self.connection_generation
                ):
                    result = False
                elif command.action == "connect":
                    result = await self._connect(reconnecting=False)
                elif command.action == "reconnect":
                    result = await self._connect(reconnecting=True)
                elif command.action == "reconcile":
                    result = await self._reconcile(command.payload)
                elif command.action == "warmup_complete":
                    result = await self._complete_warmup(command)
                elif command.action == "health":
                    result = await self._health()
                elif command.action == "refresh_quotes":
                    result = await self._refresh_quotes(command.payload)
                elif command.action == "bars_updated":
                    result = await self._bars_updated(command)
                elif command.action == "stop":
                    await self._shutdown()
                    result = True
                    if command.future and not command.future.done():
                        command.future.set_result(result)
                    return
                else:
                    raise ValueError(f"unknown subscription command: {command.action}")
                if command.future and not command.future.done():
                    command.future.set_result(result)
            except Exception as exc:
                logger.exception("订阅命令失败: action=%s", command.action)
                if command.future and not command.future.done():
                    command.future.set_exception(exc)
            finally:
                self.commands.task_done()

    async def _connect(self, *, reconnecting: bool) -> bool:
        self.connection_status = ConnectionStatus.RECONNECTING if reconnecting else ConnectionStatus.CONNECTING
        old_connection_generation = self.connection_generation
        if old_connection_generation > 0:
            self.connection_generation += 1
        await self._cancel_warmup_tasks()
        await self._cleanup_connection(old_connection_generation)

        previous_targets = dict(self.desired_targets)
        if reconnecting and self.desired_loader is not None:
            try:
                self.desired_targets = dict(await self.desired_loader())
            except Exception as exc:
                logger.warning("重连前读取 WatchList 失败，暂用已有集合: %s", exc)
        if self.client is not None:
            await self.client.close()
            self.client = None

        self.active_symbols.clear()
        self.warming_symbols.clear()
        self.removing_symbols.clear()
        for state in self.symbol_states.values():
            state.generation += 1
            state.quote_subscribed = False
            state.candlestick_1m_subscribed = False
            target = self.desired_targets.get(state.symbol)
            previous = previous_targets.get(state.symbol)
            if target is not None:
                if previous is not None and previous.market_type != target.market_type:
                    state.status = SymbolStatus.INACTIVE
                    await self.removal_callback(state.symbol)
                    await self._notify_state(state)
                state.market_type = target.market_type
                state.trading_date = None
                state.status = SymbolStatus.PENDING
                await self._notify_state(state)
            elif previous is not None:
                state.status = SymbolStatus.INACTIVE
                await self.removal_callback(state.symbol)
                await self._notify_state(state)

        delay = 1.0
        while not self._stopping:
            self.connection_generation += 1
            client = self.client_factory()
            try:
                await client.connect(self.connection_generation, self.event_sink)
                self.client = client
                logger.info("长桥连接成功: generation=%s", self.connection_generation)
                self.connection_status = ConnectionStatus.SUBSCRIBING
                for target in sorted(self.desired_targets.values(), key=lambda item: item.symbol):
                    await self._add_target(target)
                self.connection_status = ConnectionStatus.READY
                return True
            except Exception as exc:
                self.connection_status = ConnectionStatus.DISCONNECTED
                logger.warning("长桥连接失败，%.1fs 后重试: %s", delay, exc)
                failed_connection_generation = self.connection_generation
                self.connection_generation += 1
                await self._cancel_warmup_tasks(connection_generation=failed_connection_generation)
                await self._cleanup_connection(failed_connection_generation)
                try:
                    await client.close()
                except Exception:
                    pass
                self.client = None
                self.active_symbols.clear()
                self.warming_symbols.clear()
                for state in self.symbol_states.values():
                    if state.symbol not in self.desired_targets:
                        continue
                    state.generation += 1
                    state.quote_subscribed = False
                    state.candlestick_1m_subscribed = False
                    state.status = SymbolStatus.PENDING
                    await self._notify_state(state)
                retry_delay = delay + random.uniform(0, min(1.0, delay * 0.2))
                try:
                    await asyncio.wait_for(self._stop_signal.wait(), timeout=retry_delay)
                except TimeoutError:
                    pass
                delay = min(delay * 2, 30.0)
        return False

    async def _reconcile(self, desired_targets: Mapping[str, SubscriptionTarget]) -> bool:
        previous_targets = dict(self.desired_targets)
        self.desired_targets = dict(desired_targets)
        subscribed = self.active_symbols | self.warming_symbols | self.removing_symbols
        changed = {
            symbol
            for symbol in previous_targets.keys() & self.desired_targets.keys()
            if previous_targets[symbol] != self.desired_targets[symbol]
        }
        to_remove = (subscribed - self.desired_targets.keys()) | changed
        to_add = (self.desired_targets.keys() - subscribed) | changed
        for symbol in sorted(to_remove):
            await self._remove_symbol(symbol)
        for symbol in sorted(to_add):
            await self._add_target(self.desired_targets[symbol])
        return bool(to_add or to_remove)

    async def _refresh_quotes(self, symbols: set[str]) -> set[str]:
        if self.client is None:
            return set()
        eligible = {
            symbol
            for symbol in symbols
            if symbol in self.desired_targets
            and (state := self.symbol_states.get(symbol)) is not None
            and state.quote_subscribed
            and state.status not in {SymbolStatus.INACTIVE, SymbolStatus.REMOVING}
        }
        if not eligible:
            return set()
        return set(await self.client.refresh_quotes(eligible))

    async def _add_target(self, target: SubscriptionTarget) -> None:
        symbol = target.symbol
        if symbol in self.active_symbols or symbol in self.warming_symbols:
            return
        if self.client is None:
            raise RuntimeError("cannot subscribe while disconnected")
        state = self.symbol_states.get(symbol)
        if state is None:
            state = SymbolRuntimeState(symbol=symbol, market_type=target.market_type)
            self.symbol_states[symbol] = state
        else:
            state.market_type = target.market_type
            state.trading_date = None
        state.generation += 1
        state.status = SymbolStatus.WARMING
        state.error = None
        self.warming_symbols.add(symbol)
        await self._notify_state(state)
        try:
            await self.client.subscribe({symbol})
            state.quote_subscribed = True
            state.candlestick_1m_subscribed = True
            logger.info("订阅成功: %s market=%s generation=%s", symbol, target.market_type, state.generation)
            await self._notify_state(state)
        except Exception as exc:
            self.warming_symbols.discard(symbol)
            state.status = SymbolStatus.ERROR
            state.error = str(exc)
            await self._notify_state(state)
            raise

        key = WarmupTaskKey(symbol, state.generation, self.connection_generation)
        task = asyncio.create_task(self._run_warmup(key, target.market_type), name=f"market-stream-warmup-{symbol}")
        self._warmup_tasks[key] = task
        task.add_done_callback(lambda completed, task_key=key: self._discard_warmup_task(task_key, completed))

    def _discard_warmup_task(self, key: WarmupTaskKey, task: asyncio.Task[None]) -> None:
        if self._warmup_tasks.get(key) is task:
            self._warmup_tasks.pop(key, None)

    async def _run_warmup(self, key: WarmupTaskKey, market_type: MarketType) -> None:
        result: Any = None
        error: Exception | None = None
        try:
            result = await self.warmup_loader(
                key.symbol,
                market_type,
                key.symbol_generation,
                key.connection_generation,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = exc
        await self.commands.put(
            SubscriptionCommand(
                "warmup_complete",
                (key, result, error),
                connection_generation=key.connection_generation,
                symbol_generation=key.symbol_generation,
            )
        )

    async def _complete_warmup(self, command: SubscriptionCommand) -> bool:
        key, result, error = command.payload
        state = self.symbol_states.get(key.symbol)
        target = self.desired_targets.get(key.symbol)
        if (
            state is None
            or target is None
            or command.symbol_generation != state.generation
            or target.market_type != state.market_type
            or state.status != SymbolStatus.WARMING
        ):
            logger.info("丢弃陈旧 warmup 结果: %s generation=%s", key.symbol, command.symbol_generation)
            return False

        def finalize(count: int, final_error: Exception | None, trading_date: date | None) -> None:
            state.bars_count = count
            state.trading_date = trading_date
            state.warmed_at = utc_now()
            state.error = str(final_error) if final_error is not None else None
            if final_error is not None:
                state.status = SymbolStatus.ERROR
            elif count >= self.minimum_history_bars:
                state.status = SymbolStatus.ACTIVE
            else:
                state.status = SymbolStatus.INSUFFICIENT_HISTORY
            self.warming_symbols.discard(state.symbol)
            self.active_symbols.add(state.symbol)

        applied = await self.warmup_apply(state, key.connection_generation, result, error, finalize)
        if not applied:
            return False
        logger.info("warmup 完成: %s bars=%s status=%s", state.symbol, state.bars_count, state.status)
        await self._notify_state(state)
        return True

    async def _remove_symbol(self, symbol: str) -> None:
        state = self.symbol_states.get(symbol)
        if state is None or state.status in {SymbolStatus.INACTIVE, SymbolStatus.REMOVING}:
            return
        await self._cancel_warmup_tasks(symbol=symbol)
        state.generation += 1
        state.status = SymbolStatus.REMOVING
        self.removing_symbols.add(symbol)
        self.active_symbols.discard(symbol)
        self.warming_symbols.discard(symbol)
        await self._notify_state(state)
        unsubscribe_error: Exception | None = None
        try:
            if self.client is not None and (state.quote_subscribed or state.candlestick_1m_subscribed):
                await self.client.unsubscribe({symbol})
            logger.info("取消订阅成功: %s", symbol)
        except Exception as exc:
            unsubscribe_error = exc
            logger.warning("取消订阅失败，将重建连接: symbol=%s error=%s", symbol, exc)
        finally:
            state.quote_subscribed = False
            state.candlestick_1m_subscribed = False
            state.status = SymbolStatus.INACTIVE
            self.removing_symbols.discard(symbol)
            await self.removal_callback(symbol)
            await self._notify_state(state)
        if unsubscribe_error is not None:
            await self._connect(reconnecting=True)

    async def _health(self) -> bool:
        if self.client is None:
            await self._connect(reconnecting=True)
            return False
        try:
            await self.client.health_check()
            return True
        except Exception as exc:
            logger.warning("长桥连接断开，开始重连: %s", exc)
            await self._connect(reconnecting=True)
            return False

    async def _bars_updated(self, command: SubscriptionCommand) -> bool:
        symbol, count = command.payload
        state = self.symbol_states.get(symbol)
        if state is None or state.generation != command.symbol_generation:
            return False
        state.bars_count = count
        if (
            state.status in {SymbolStatus.INSUFFICIENT_HISTORY, SymbolStatus.ERROR}
            and count >= self.minimum_history_bars
        ):
            state.status = SymbolStatus.ACTIVE
            state.error = None
            self.active_symbols.add(symbol)
            await self._notify_state(state)
        return True

    async def _cancel_warmup_tasks(
        self,
        *,
        connection_generation: int | None = None,
        symbol: str | None = None,
    ) -> None:
        selected = {
            key: task
            for key, task in self._warmup_tasks.items()
            if (connection_generation is None or key.connection_generation == connection_generation)
            and (symbol is None or key.symbol == symbol)
        }
        if not selected:
            return
        for task in selected.values():
            task.cancel()
        await asyncio.gather(*selected.values(), return_exceptions=True)
        for key in selected:
            self._warmup_tasks.pop(key, None)

    async def _cleanup_connection(self, connection_generation: int) -> None:
        if connection_generation > 0 and self.connection_cleanup_callback is not None:
            await self.connection_cleanup_callback(connection_generation)

    async def _notify_state(self, state: SymbolRuntimeState) -> None:
        logger.info(
            "symbol 状态: symbol=%s market=%s status=%s generation=%s",
            state.symbol,
            state.market_type,
            state.status,
            state.generation,
        )
        try:
            await self.state_callback(state)
        except Exception as exc:
            logger.warning("写入订阅状态失败: symbol=%s error=%s", state.symbol, exc)

    async def _shutdown(self) -> None:
        old_connection_generation = self.connection_generation
        if old_connection_generation > 0:
            self.connection_generation += 1
        await self._cancel_warmup_tasks()
        await self._cleanup_connection(old_connection_generation)
        if self.client is not None:
            subscribed = self.active_symbols | self.warming_symbols
            if subscribed:
                try:
                    await self.client.unsubscribe(subscribed)
                except Exception as exc:
                    logger.warning("停止时取消订阅失败: %s", exc)
            await self.client.close()
        self.connection_status = ConnectionStatus.STOPPED

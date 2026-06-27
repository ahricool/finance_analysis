"""Serialized subscription lifecycle and generation protection."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from finance_analysis.core.time import utc_now
from finance_analysis.market_stream.symbol_state import ConnectionStatus, SymbolRuntimeState, SymbolStatus

logger = logging.getLogger(__name__)

StateCallback = Callable[[SymbolRuntimeState], Awaitable[None]]
WarmupLoader = Callable[[str, int, int], Awaitable[Any]]
WarmupApply = Callable[[str, int, Any, Exception | None], Awaitable[int]]
RemovalCallback = Callable[[str], Awaitable[None]]
DesiredLoader = Callable[[], Awaitable[set[str]]]


@dataclass(slots=True)
class SubscriptionCommand:
    action: str
    payload: Any = None
    connection_generation: int | None = None
    symbol_generation: int | None = None
    future: asyncio.Future[Any] | None = None


class SubscriptionManager:
    """Own all calls to the streaming client and all symbol state transitions."""

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
        minimum_history_bars: int = 15,
    ) -> None:
        self.client_factory = client_factory
        self.event_sink = event_sink
        self.warmup_loader = warmup_loader
        self.warmup_apply = warmup_apply
        self.state_callback = state_callback
        self.removal_callback = removal_callback
        self.desired_loader = desired_loader
        self.minimum_history_bars = minimum_history_bars
        self.commands: asyncio.Queue[SubscriptionCommand] = asyncio.Queue()
        self.desired_symbols: set[str] = set()
        self.active_symbols: set[str] = set()
        self.warming_symbols: set[str] = set()
        self.removing_symbols: set[str] = set()
        self.symbol_states: dict[str, SymbolRuntimeState] = {}
        self.connection_generation = 0
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.client: Any | None = None
        self._worker: asyncio.Task[None] | None = None
        self._warmup_tasks: set[asyncio.Task[None]] = set()
        self._stopping = False
        self._stop_signal = asyncio.Event()

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="market-stream-subscriptions")
        await self._request("connect")

    async def reconcile(self, desired_symbols: set[str], *, generation: int | None = None) -> None:
        await self._request("reconcile", set(desired_symbols), connection_generation=generation)

    async def health_check(self) -> bool:
        return bool(await self._request("health"))

    async def reconnect(self) -> None:
        await self._request("reconnect")

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
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
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
        previous_desired = set(self.desired_symbols)
        if reconnecting and self.desired_loader is not None:
            try:
                self.desired_symbols = await self.desired_loader()
            except Exception as exc:
                logger.warning("重连前读取 WatchList 失败，暂用已有集合: %s", exc)
        if self.client is not None:
            await self.client.close()
            self.client = None
        self.active_symbols.clear()
        self.warming_symbols.clear()
        for state in self.symbol_states.values():
            state.generation += 1
            state.quote_subscribed = False
            state.candlestick_1m_subscribed = False
            if state.symbol in self.desired_symbols:
                state.status = SymbolStatus.PENDING
                await self._notify_state(state)
            elif state.symbol in previous_desired:
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
                for symbol in sorted(self.desired_symbols):
                    await self._add_symbol(symbol)
                self.connection_status = ConnectionStatus.READY
                return True
            except Exception as exc:
                self.connection_status = ConnectionStatus.DISCONNECTED
                logger.warning("长桥连接失败，%.1fs 后重试: %s", delay, exc)
                try:
                    await client.close()
                except Exception:
                    pass
                self.client = None
                self.active_symbols.clear()
                self.warming_symbols.clear()
                for state in self.symbol_states.values():
                    if state.symbol not in self.desired_symbols:
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

    async def _reconcile(self, desired_symbols: set[str]) -> bool:
        self.desired_symbols = set(desired_symbols)
        subscribed = self.active_symbols | self.warming_symbols | self.removing_symbols
        to_remove = subscribed - self.desired_symbols
        to_add = self.desired_symbols - subscribed
        for symbol in sorted(to_remove):
            await self._remove_symbol(symbol)
        for symbol in sorted(to_add):
            await self._add_symbol(symbol)
        return bool(to_add or to_remove)

    async def _add_symbol(self, symbol: str) -> None:
        if symbol in self.active_symbols or symbol in self.warming_symbols:
            return
        if self.client is None:
            raise RuntimeError("cannot subscribe while disconnected")
        state = self.symbol_states.setdefault(symbol, SymbolRuntimeState(symbol=symbol))
        state.generation += 1
        state.status = SymbolStatus.WARMING
        state.error = None
        self.warming_symbols.add(symbol)
        await self._notify_state(state)
        generation = state.generation
        try:
            await self.client.subscribe({symbol})
            state.quote_subscribed = True
            state.candlestick_1m_subscribed = True
            logger.info("订阅成功: %s generation=%s", symbol, generation)
            await self._notify_state(state)
        except Exception as exc:
            self.warming_symbols.discard(symbol)
            state.status = SymbolStatus.ERROR
            state.error = str(exc)
            await self._notify_state(state)
            raise

        task = asyncio.create_task(
            self._run_warmup(symbol, generation, self.connection_generation),
            name=f"market-stream-warmup-{symbol}",
        )
        self._warmup_tasks.add(task)
        task.add_done_callback(self._warmup_tasks.discard)

    async def _run_warmup(self, symbol: str, symbol_generation: int, connection_generation: int) -> None:
        result: Any = None
        error: Exception | None = None
        try:
            result = await self.warmup_loader(symbol, symbol_generation, connection_generation)
        except Exception as exc:
            error = exc
        await self.commands.put(
            SubscriptionCommand(
                "warmup_complete",
                (symbol, result, error),
                connection_generation=connection_generation,
                symbol_generation=symbol_generation,
            )
        )

    async def _complete_warmup(self, command: SubscriptionCommand) -> bool:
        symbol, result, error = command.payload
        state = self.symbol_states.get(symbol)
        if (
            state is None
            or command.symbol_generation != state.generation
            or symbol not in self.desired_symbols
            or state.status != SymbolStatus.WARMING
        ):
            logger.info("丢弃陈旧 warmup 结果: %s generation=%s", symbol, command.symbol_generation)
            return False
        if error is not None:
            state.status = SymbolStatus.ERROR
            state.error = str(error)
            self.warming_symbols.discard(symbol)
            # The streaming subscriptions remain valid even though historical
            # recovery failed. Keep the symbol in the subscribed set and allow
            # live candles to move it to ACTIVE once enough bars accumulate.
            self.active_symbols.add(symbol)
            await self._notify_state(state)
            return False

        bars_count = await self.warmup_apply(symbol, state.generation, result, None)
        if state.generation != command.symbol_generation or symbol not in self.desired_symbols:
            return False
        state.bars_count = bars_count
        state.warmed_at = utc_now()
        state.status = (
            SymbolStatus.ACTIVE if bars_count >= self.minimum_history_bars else SymbolStatus.INSUFFICIENT_HISTORY
        )
        self.warming_symbols.discard(symbol)
        self.active_symbols.add(symbol)
        logger.info("warmup 完成: %s bars=%s status=%s", symbol, bars_count, state.status)
        await self._notify_state(state)
        return True

    async def _remove_symbol(self, symbol: str) -> None:
        state = self.symbol_states.setdefault(symbol, SymbolRuntimeState(symbol=symbol))
        if state.status in {SymbolStatus.INACTIVE, SymbolStatus.REMOVING}:
            return
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

    async def _notify_state(self, state: SymbolRuntimeState) -> None:
        logger.info("symbol 状态: symbol=%s status=%s generation=%s", state.symbol, state.status, state.generation)
        try:
            await self.state_callback(state)
        except Exception as exc:
            logger.warning("写入订阅状态失败: symbol=%s error=%s", state.symbol, exc)

    async def _shutdown(self) -> None:
        for task in tuple(self._warmup_tasks):
            task.cancel()
        if self._warmup_tasks:
            await asyncio.gather(*self._warmup_tasks, return_exceptions=True)
        if self.client is not None:
            subscribed = self.active_symbols | self.warming_symbols
            if subscribed:
                try:
                    await self.client.unsubscribe(subscribed)
                except Exception as exc:
                    logger.warning("停止时取消订阅失败: %s", exc)
            await self.client.close()
        self.connection_status = ConnectionStatus.STOPPED

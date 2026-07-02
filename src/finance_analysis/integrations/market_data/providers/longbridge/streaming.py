"""Longbridge 4.x async streaming client adapter."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from finance_analysis.integrations.market_data.providers.longbridge.market import build_longbridge_config
from finance_analysis.integrations.market_data.providers.longbridge.normalizer import (
    MarketEvent,
    normalize_candlestick,
    normalize_quote,
    normalize_quote_reference,
    normalize_quote_snapshot,
)


EventSink = Callable[[MarketEvent], None]
logger = logging.getLogger(__name__)


class LongbridgeStreamingClient:
    """Small adapter that keeps all SDK-specific signatures in one module."""

    def __init__(self) -> None:
        self.context: Any | None = None
        self.generation = 0
        self.event_sink: EventSink | None = None

    async def connect(self, generation: int, event_sink: EventSink) -> None:
        from longbridge.openapi import AsyncQuoteContext

        loop = asyncio.get_running_loop()
        self.generation = generation
        self.event_sink = event_sink
        config = await asyncio.to_thread(build_longbridge_config)
        self.context = await asyncio.to_thread(AsyncQuoteContext.create, config, loop)
        self.context.set_on_quote(
            lambda symbol, event: loop.call_soon_threadsafe(
                event_sink, normalize_quote(symbol, event, generation=generation)
            )
        )
        self.context.set_on_candlestick(
            lambda symbol, event: loop.call_soon_threadsafe(
                event_sink, normalize_candlestick(symbol, event, generation=generation)
            )
        )

    async def subscribe(self, symbols: set[str]) -> None:
        if not symbols:
            return
        if self.context is None:
            raise RuntimeError("Longbridge streaming context is disconnected")
        from longbridge.openapi import Period, SubType, TradeSessions

        ordered = sorted(symbols)
        # No pushes can arrive before this subscription call, so the full
        # snapshot is safe to use as the initial quote state.
        await self.refresh_quotes(symbols, reference_only=False)
        await self.context.subscribe(ordered, [SubType.Quote])
        for symbol in ordered:
            await self.context.subscribe_candlesticks(symbol, Period.Min_1, TradeSessions.Intraday)

    async def refresh_quotes(
        self,
        symbols: set[str],
        *,
        reference_only: bool = True,
    ) -> set[str]:
        """Fetch quote snapshots, optionally emitting only push-missing reference fields."""
        if not symbols:
            return set()
        if self.context is None:
            raise RuntimeError("Longbridge streaming context is disconnected")
        ordered = sorted(symbols)
        try:
            snapshots = await self.context.quote(ordered)
        except Exception as exc:
            # Quote pushes do not contain prev_close. Keep streaming available
            # when the initial snapshot fails, but make the missing reference
            # price observable so the next reconnect can retry it.
            logger.warning("长桥行情快照失败: symbols=%s error=%s", ordered, exc)
            return set()
        if self.event_sink is None:
            raise RuntimeError("Longbridge streaming event sink is unavailable")
        refreshed: set[str] = set()
        for snapshot in snapshots:
            symbol = str(getattr(snapshot, "symbol", "") or "")
            if not symbol:
                logger.warning("长桥行情快照缺少证券代码，已忽略")
                continue
            normalizer = normalize_quote_reference if reference_only else normalize_quote_snapshot
            self.event_sink(normalizer(symbol, snapshot, generation=self.generation))
            refreshed.add(symbol)
        return refreshed

    async def unsubscribe(self, symbols: set[str]) -> None:
        if not symbols or self.context is None:
            return
        from longbridge.openapi import Period, SubType

        ordered = sorted(symbols)
        for symbol in ordered:
            await self.context.unsubscribe_candlesticks(symbol, Period.Min_1)
        await self.context.unsubscribe(ordered, [SubType.Quote])

    async def health_check(self) -> None:
        if self.context is None:
            raise RuntimeError("Longbridge streaming context is disconnected")
        await self.context.subscriptions()

    async def close(self) -> None:
        # longbridge 4.3.2 does not expose close() on AsyncQuoteContext. Dropping
        # the context releases the Rust-owned connection after callbacks detach.
        self.context = None
        self.event_sink = None

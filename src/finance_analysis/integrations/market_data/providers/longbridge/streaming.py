"""Longbridge 4.x async streaming client adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from finance_analysis.integrations.market_data.providers.longbridge.market import build_longbridge_config
from finance_analysis.integrations.market_data.providers.longbridge.normalizer import (
    MarketEvent,
    normalize_candlestick,
    normalize_quote,
)


EventSink = Callable[[MarketEvent], None]


class LongbridgeStreamingClient:
    """Small adapter that keeps all SDK-specific signatures in one module."""

    def __init__(self) -> None:
        self.context: Any | None = None
        self.generation = 0

    async def connect(self, generation: int, event_sink: EventSink) -> None:
        from longbridge.openapi import AsyncQuoteContext

        loop = asyncio.get_running_loop()
        self.generation = generation
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
        await self.context.subscribe(ordered, [SubType.Quote])
        for symbol in ordered:
            await self.context.subscribe_candlesticks(symbol, Period.Min_1, TradeSessions.Intraday)

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

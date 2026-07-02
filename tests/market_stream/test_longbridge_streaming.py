from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from finance_analysis.integrations.market_data.providers.longbridge.streaming import (
    LongbridgeStreamingClient,
)


class FakeQuoteContext:
    def __init__(self, *, snapshot_error: Exception | None = None) -> None:
        self.snapshot_error = snapshot_error
        self.operations: list[tuple[str, object]] = []

    async def quote(self, symbols):
        self.operations.append(("quote", list(symbols)))
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return [
            SimpleNamespace(
                symbol=symbol,
                last_done="102.50",
                prev_close="100.00",
                open="101.00",
                high="103.00",
                low="99.50",
                volume=123,
                turnover="12345.67",
                timestamp=datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc),
            )
            for symbol in symbols
        ]

    async def subscribe(self, symbols, sub_types):
        self.operations.append(("subscribe", list(symbols)))

    async def subscribe_candlesticks(self, symbol, period, trade_sessions):
        self.operations.append(("subscribe_candlesticks", symbol))


@pytest.mark.asyncio
async def test_subscribe_seeds_prev_close_before_starting_pushes() -> None:
    context = FakeQuoteContext()
    events = []
    client = LongbridgeStreamingClient()
    client.context = context
    client.generation = 7
    client.event_sink = events.append

    await client.subscribe({"AAPL.US"})

    assert [operation[0] for operation in context.operations] == [
        "quote",
        "subscribe",
        "subscribe_candlesticks",
    ]
    assert len(events) == 1
    assert events[0].symbol == "AAPL.US"
    assert events[0].connection_generation == 7
    assert events[0].event_type == "quote_snapshot"
    assert events[0].payload["last_price"] == "102.50"
    assert events[0].payload["pre_close"] == "100.00"


@pytest.mark.asyncio
async def test_daily_refresh_only_emits_reference_price() -> None:
    context = FakeQuoteContext()
    events = []
    client = LongbridgeStreamingClient()
    client.context = context
    client.generation = 8
    client.event_sink = events.append

    assert await client.refresh_quotes({"AAPL.US"}) == {"AAPL.US"}

    assert len(events) == 1
    assert events[0].event_type == "quote_reference"
    assert events[0].payload == {"pre_close": "100.00"}


@pytest.mark.asyncio
async def test_snapshot_failure_does_not_block_realtime_subscription(caplog) -> None:
    context = FakeQuoteContext(snapshot_error=RuntimeError("snapshot unavailable"))
    client = LongbridgeStreamingClient()
    client.context = context
    client.generation = 3
    client.event_sink = lambda event: None

    await client.subscribe({"AAPL.US"})

    assert [operation[0] for operation in context.operations] == [
        "quote",
        "subscribe",
        "subscribe_candlesticks",
    ]
    assert "长桥行情快照失败" in caplog.text

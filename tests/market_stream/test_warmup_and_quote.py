from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.integrations.market_data.providers.longbridge.normalizer import MarketEvent
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.market_stream.service import MarketStreamService, WarmupResult
from finance_analysis.market_stream.symbol_state import SymbolRuntimeState, SymbolStatus
from finance_analysis.market_stream.warmup import merge_warmup_bars
from tests.market_stream.fakes import FakeRedis, FakeStreamingClient


BASE = datetime(2026, 6, 26, 14, 30, tzinfo=timezone.utc)


def bar(
    minute: int,
    *,
    close: str = "10",
    confirmed: bool = True,
    received: int = 0,
) -> CandleState:
    when = BASE + timedelta(minutes=minute)
    return CandleState(
        symbol="AAPL.US",
        bar_time=when,
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal(close),
        volume=10,
        turnover=Decimal("100"),
        trade_session="Intraday",
        confirmed=confirmed,
        received_at=when + timedelta(seconds=received),
    )


def service(redis: FakeRedis | None = None) -> MarketStreamService:
    redis = redis or FakeRedis()
    config = MarketStreamConfig(redis_url="redis://fake", bar_limit=420)
    return MarketStreamService(
        config=config,
        repository=RealtimeStateRepository(redis, bar_limit=420),
        client_factory=FakeStreamingClient,
    )


def test_quote_partial_merge_stale_sequence_and_timestamps() -> None:
    quote = QuoteState(symbol="AAPL.US")
    first = BASE
    assert quote.merge(
        {"last_price": "100", "open": "98", "volume": 10, "sequence": 2},
        event_time=first,
        received_at=first,
    )
    assert quote.merge(
        {"last_price": "101", "sequence": 3},
        event_time=first + timedelta(seconds=1),
        received_at=first + timedelta(seconds=2),
    )
    assert quote.open == Decimal("98")
    assert quote.volume == 10
    assert quote.last_price == Decimal("101")
    assert not quote.merge(
        {"last_price": "1", "open": None, "sequence": 1},
        event_time=first,
        received_at=first,
    )
    assert quote.last_price == Decimal("101")
    assert quote.received_at == first + timedelta(seconds=2)


def test_warmup_merge_deduplicates_confirmed_history_and_latest_current() -> None:
    historical = [bar(0), bar(1, close="10", confirmed=True), bar(2, close="10", confirmed=False)]
    realtime = [
        bar(1, close="11", confirmed=False, received=50),
        bar(2, close="11", confirmed=False, received=10),
        bar(2, close="12", confirmed=False, received=20),
    ]
    merged = merge_warmup_bars(historical, realtime, limit=420)
    assert len(merged) == 3
    assert merged[1].close == Decimal("10")
    assert merged[2].close == Decimal("12")
    assert [item.bar_time for item in merged] == sorted(item.bar_time for item in merged)


@pytest.mark.asyncio
async def test_stale_connection_event_is_dropped_and_warming_candle_is_buffered() -> None:
    app = service()
    app.manager.connection_generation = 2
    app.manager.desired_symbols = {"AAPL.US"}
    app.manager.symbol_states["AAPL.US"] = SymbolRuntimeState(
        symbol="AAPL.US", status=SymbolStatus.WARMING, generation=1
    )
    stale = MarketEvent("quote", "AAPL.US", BASE, BASE, None, None, {"last_price": "1"}, 1)
    await app._handle_event(stale)
    assert "AAPL.US" not in app.quotes

    event = MarketEvent(
        "candle_1m",
        "AAPL.US",
        BASE,
        BASE,
        None,
        "Intraday",
        {
            "bar_time": BASE,
            "open": "10",
            "high": "12",
            "low": "9",
            "close": "11",
            "volume": 10,
            "turnover": "100",
            "trade_session": "Intraday",
            "confirmed": False,
        },
        2,
    )
    await app._handle_event(event)
    assert len(app.warming_buffers["AAPL.US"]) == 1


@pytest.mark.asyncio
async def test_warmup_apply_merges_buffer_and_generation_guard() -> None:
    app = service()
    app.manager.desired_symbols = {"AAPL.US"}
    app.manager.symbol_states["AAPL.US"] = SymbolRuntimeState(
        symbol="AAPL.US", status=SymbolStatus.WARMING, generation=3
    )
    app.warming_buffers["AAPL.US"] = {bar(2, close="12", confirmed=False).identity: bar(2, close="12", confirmed=False)}
    result = WarmupResult("AAPL.US", [], [bar(0), bar(1), bar(2, close="10", confirmed=False)], 0.1)
    count = await app._apply_warmup("AAPL.US", 3, result, None)
    assert count == 3
    assert app.bars_1m["AAPL.US"][-1].close == Decimal("12")
    assert len(await app.repository.get_recent_bars("AAPL.US", 10)) == 3

    stale_count = await app._apply_warmup("AAPL.US", 2, result, None)
    assert stale_count == 0


@pytest.mark.asyncio
async def test_warmup_uses_redis_cache_before_history() -> None:
    app = service()
    now = datetime.now(ZoneInfo("America/New_York")).replace(hour=12, second=0, microsecond=0)
    cached_bars = []
    for index in range(15):
        cached = bar(index)
        cached.bar_time = now.replace(minute=index).astimezone(timezone.utc)
        cached_bars.append(cached)
    await app.repository.upsert_bars("AAPL.US", cached_bars)

    class FailingHistory:
        async def fetch(self, symbol, count):
            raise AssertionError("history should not be called")

    app.history_loader = FailingHistory()
    result = await app._load_warmup("AAPL.US", 1, 1)
    assert len(result.cached) == 15
    assert result.historical == []


@pytest.mark.asyncio
async def test_incomplete_redis_cache_falls_back_to_history() -> None:
    app = service()
    current = bar(0)
    current.bar_time = datetime.now(ZoneInfo("America/New_York")).replace(
        hour=12, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)
    await app.repository.upsert_bars("AAPL.US", [current])
    calls = []

    class History:
        async def fetch(self, symbol, count):
            calls.append((symbol, count))
            return [bar(1)]

    app.history_loader = History()
    result = await app._load_warmup("AAPL.US", 1, 1)
    assert calls == [("AAPL.US", 420)]
    assert len(result.historical) == 1


@pytest.mark.asyncio
async def test_warmup_concurrency_is_limited() -> None:
    app = service()
    app.warmup_semaphore = asyncio.Semaphore(2)
    current = 0
    maximum = 0

    class History:
        async def fetch(self, symbol, count):
            nonlocal current, maximum
            current += 1
            maximum = max(maximum, current)
            await asyncio.sleep(0.02)
            current -= 1
            return []

    app.history_loader = History()
    await asyncio.gather(*(app._load_warmup(f"S{i}.US", 1, 1) for i in range(6)))
    assert maximum == 2

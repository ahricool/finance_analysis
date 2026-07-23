from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_analysis.integrations.market_data.providers.longbridge.normalizer import MarketEvent
from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.market_stream.service import MarketStreamService, WarmupResult
from finance_analysis.market_stream.subscription_manager import SubscriptionCommand, WarmupTaskKey
from finance_analysis.market_stream.symbol_state import SubscriptionTarget, SymbolRuntimeState, SymbolStatus
from finance_analysis.market_stream.warmup import merge_warmup_bars
from tests.market_stream.fakes import FakeRedis, FakeStreamingClient

BASE = datetime(2026, 6, 26, 13, 30, tzinfo=timezone.utc)


def bar(
    minute: int,
    *,
    symbol: str = "AAPL.US",
    close: str = "10",
    confirmed: bool = True,
    received: int = 0,
) -> CandleState:
    when = BASE + timedelta(minutes=minute)
    return CandleState(
        symbol=symbol,
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


def candle_event(candle: CandleState, connection_generation: int) -> MarketEvent:
    return MarketEvent(
        "candle_1m",
        candle.symbol,
        candle.bar_time,
        candle.received_at,
        None,
        candle.trade_session,
        {
            "bar_time": candle.bar_time,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "turnover": candle.turnover,
            "trade_session": candle.trade_session,
            "confirmed": candle.confirmed,
        },
        connection_generation,
    )


def quote_event(
    price: str,
    sequence: int,
    connection_generation: int,
    *,
    received_at: datetime | None = None,
    pre_close: str | None = None,
) -> MarketEvent:
    received_at = received_at or BASE + timedelta(seconds=sequence)
    payload = {"last_price": price, "sequence": sequence, "trade_session": "Intraday"}
    if pre_close is not None:
        payload["pre_close"] = pre_close
    return MarketEvent(
        "quote",
        "AAPL.US",
        received_at,
        received_at,
        sequence,
        "Intraday",
        payload,
        connection_generation,
    )


def quote_reference_event(pre_close: str, connection_generation: int) -> MarketEvent:
    received_at = BASE + timedelta(seconds=30)
    return MarketEvent(
        "quote_reference",
        "AAPL.US",
        received_at,
        received_at,
        None,
        None,
        {"pre_close": pre_close},
        connection_generation,
    )


def service(redis: FakeRedis | None = None, repository=None) -> MarketStreamService:
    redis = redis or FakeRedis()
    config = MarketStreamConfig(redis_url="redis://fake", bar_limit=420)
    return MarketStreamService(
        config=config,
        repository=repository or RealtimeStateRepository(redis, bar_limit=420),
        client_factory=FakeStreamingClient,
    )


def set_warming(app: MarketStreamService, *, generation: int = 3, connection: int = 2) -> SymbolRuntimeState:
    target = SubscriptionTarget("AAPL.US", "US")
    state = SymbolRuntimeState(
        symbol=target.symbol,
        market_type=target.market_type,
        status=SymbolStatus.WARMING,
        generation=generation,
    )
    app.manager.desired_targets = {target.symbol: target}
    app.manager.symbol_states[target.symbol] = state
    app.manager.connection_generation = connection
    app.manager.warming_symbols.add(target.symbol)
    return state


def test_quote_partial_merge_stale_sequence_and_timestamps() -> None:
    quote = QuoteState(symbol="AAPL.US")
    assert quote.merge(
        {"last_price": "100", "open": "98", "volume": 10, "sequence": 2},
        event_time=BASE,
        received_at=BASE,
    )
    assert quote.merge(
        {"last_price": "101", "sequence": 3},
        event_time=BASE + timedelta(seconds=1),
        received_at=BASE + timedelta(seconds=2),
    )
    assert quote.open == Decimal("98")
    assert quote.volume == 10
    assert not quote.merge(
        {"last_price": "1", "sequence": 1},
        event_time=BASE,
        received_at=BASE,
    )
    assert quote.last_price == Decimal("101")


def test_warmup_merge_deduplicates_confirmed_history_and_latest_current() -> None:
    historical = [bar(0), bar(1, confirmed=True), bar(2, confirmed=False)]
    realtime = [
        bar(1, close="11", confirmed=False, received=50),
        bar(2, close="11", confirmed=False, received=10),
        bar(2, close="12", confirmed=False, received=20),
    ]
    merged = merge_warmup_bars(historical, realtime, limit=420)
    assert len(merged) == 3
    assert merged[1].close == Decimal("10")
    assert merged[2].close == Decimal("12")


@pytest.mark.asyncio
async def test_stale_connection_event_is_dropped_and_buffer_is_generation_scoped() -> None:
    app = service()
    state = set_warming(app)
    await app._handle_event(candle_event(bar(0), 1))
    assert not app.warming_buffers

    await app._handle_event(candle_event(bar(0), 2))
    key = WarmupTaskKey("AAPL.US", state.generation, 2)
    assert len(app.warming_buffers[key]) == 1


class BlockingRepository(RealtimeStateRepository):
    def __init__(self, redis) -> None:
        super().__init__(redis)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def upsert_bars(self, symbol, bars) -> None:
        self.entered.set()
        await self.release.wait()
        await super().upsert_bars(symbol, bars)


@pytest.mark.asyncio
async def test_warmup_finalization_is_atomic_while_redis_write_is_blocked() -> None:
    redis = FakeRedis()
    repository = BlockingRepository(redis)
    app = service(redis, repository)
    state = set_warming(app)
    key = WarmupTaskKey("AAPL.US", state.generation, app.manager.connection_generation)
    initial_buffer = bar(14, close="11", confirmed=False)
    app.warming_buffers[key] = {initial_buffer.identity: initial_buffer}
    history = [bar(index) for index in range(15)]
    result = WarmupResult("AAPL.US", "US", [], history, 0.1)
    command = SubscriptionCommand(
        "warmup_complete",
        (key, result, None),
        connection_generation=key.connection_generation,
        symbol_generation=key.symbol_generation,
    )

    completing = asyncio.create_task(app.manager._complete_warmup(command))
    await repository.entered.wait()
    assert state.status == SymbolStatus.ACTIVE

    arrived_during_redis = bar(15, close="12", confirmed=False, received=30)
    await app._handle_event(candle_event(arrived_during_redis, key.connection_generation))
    repository.release.set()
    assert await completing

    bars = list(app.bars_1m["AAPL.US"])
    assert arrived_during_redis.identity in {item.identity for item in bars}
    assert len({item.identity for item in bars}) == len(bars)
    assert key not in app.warming_buffers


@pytest.mark.asyncio
async def test_stale_warmup_result_cannot_activate_new_generation() -> None:
    app = service()
    state = set_warming(app, generation=4, connection=3)
    stale_key = WarmupTaskKey("AAPL.US", 3, 2)
    result = WarmupResult("AAPL.US", "US", [], [bar(0)], 0.1)
    command = SubscriptionCommand(
        "warmup_complete",
        (stale_key, result, None),
        connection_generation=2,
        symbol_generation=3,
    )
    assert not await app.manager._complete_warmup(command)
    assert state.status == SymbolStatus.WARMING


class FailingRepository(RealtimeStateRepository):
    async def upsert_bars(self, symbol, bars) -> None:
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_redis_failure_after_activation_does_not_lose_memory_bars() -> None:
    app = service(repository=FailingRepository(FakeRedis()))
    state = set_warming(app)
    key = WarmupTaskKey("AAPL.US", state.generation, app.manager.connection_generation)
    buffered = bar(1, close="12", confirmed=False)
    app.warming_buffers[key] = {buffered.identity: buffered}
    finalized = []

    def finalize(count, error, trading_date):
        finalized.append((count, error, trading_date))
        state.status = SymbolStatus.ACTIVE

    result = WarmupResult("AAPL.US", "US", [], [bar(0)], 0.1)
    assert await app._apply_warmup(state, key.connection_generation, result, None, finalize)
    assert [item.close for item in app.bars_1m["AAPL.US"]] == [Decimal("10"), Decimal("12")]
    assert finalized[0][0] == 2
    assert app.redis_degraded
    assert len(app.pending_bars["AAPL.US"]) == 2

    assert await app._flush_pending_redis()
    assert "AAPL.US" not in app.pending_bars
    restored = await app.repository.get_recent_bars("AAPL.US", 10)
    assert [item.close for item in restored] == [Decimal("10"), Decimal("12")]


@pytest.mark.asyncio
async def test_connection_cleanup_removes_only_old_generation_buffers() -> None:
    app = service()
    old = WarmupTaskKey("AAPL.US", 1, 1)
    current = WarmupTaskKey("AAPL.US", 2, 2)
    app.warming_buffers[old] = {bar(0).identity: bar(0)}
    app.warming_buffers[current] = {bar(1).identity: bar(1)}
    await app._cleanup_connection_buffers(1)
    assert old not in app.warming_buffers
    assert current in app.warming_buffers


@pytest.mark.asyncio
async def test_connection_cleanup_resets_quote_sequence_for_new_connection() -> None:
    app = service()
    target = SubscriptionTarget("AAPL.US", "US")
    state = SymbolRuntimeState(
        symbol=target.symbol,
        market_type=target.market_type,
        status=SymbolStatus.ACTIVE,
        generation=1,
    )
    app.manager.desired_targets = {target.symbol: target}
    app.manager.symbol_states[target.symbol] = state
    app.manager.connection_generation = 2

    await app._handle_event(quote_event("100", 100, 2))
    assert app.quotes["AAPL.US"].sequence == 100
    assert "AAPL.US" in app.pending_quotes

    app.manager.connection_generation = 3
    await app._cleanup_connection_buffers(2)
    assert app.quotes["AAPL.US"].sequence is None
    assert "AAPL.US" not in app.pending_quotes

    await app._handle_event(quote_event("101", 1, 3))
    assert app.quotes["AAPL.US"].last_price == Decimal("101")
    assert app.quotes["AAPL.US"].sequence == 1


def activate(app: MarketStreamService, *, connection: int = 2) -> SymbolRuntimeState:
    state = set_warming(app, connection=connection)
    state.status = SymbolStatus.ACTIVE
    app.manager.warming_symbols.discard(state.symbol)
    app.manager.active_symbols.add(state.symbol)
    return state


@pytest.mark.asyncio
async def test_unconfirmed_candle_does_not_update_trend_but_confirmation_does() -> None:
    redis = FakeRedis()
    app = service(redis)
    activate(app)
    for index in range(4):
        await app._handle_event(candle_event(bar(index, close=str(10 + index / 10)), 2))
    before = redis.pipeline_executes
    stored_before = dict(redis.hashes[keys.trend_key("AAPL.US")])
    pattern_before = dict(redis.hashes[keys.pattern_key("AAPL.US")])
    await app._handle_event(candle_event(bar(4, close="10.4", confirmed=False), 2))
    assert redis.hashes[keys.trend_key("AAPL.US")] == stored_before
    assert redis.hashes[keys.pattern_key("AAPL.US")] == pattern_before
    assert redis.pipeline_executes == before

    await app._handle_event(candle_event(bar(4, close="10.4", confirmed=True, received=61), 2))
    restored = await app.repository.get_trend_state("AAPL.US")
    assert restored is not None
    assert restored.state == "above"
    assert restored.effective_period == 5
    pattern_state = await app.repository.get_pattern_state("AAPL.US")
    assert pattern_state is not None
    assert pattern_state.status == "insufficient"


@pytest.mark.asyncio
async def test_duplicate_confirmed_candle_does_not_write_trend_twice() -> None:
    redis = FakeRedis()
    app = service(redis)
    activate(app)
    value = bar(0, confirmed=True, received=61)
    await app._handle_event(candle_event(value, 2))
    before = redis.pipeline_executes
    await app._handle_event(candle_event(bar(0, confirmed=True, received=120), 2))
    assert redis.pipeline_executes == before


@pytest.mark.asyncio
async def test_trend_calculation_failure_does_not_stop_event_processing(monkeypatch) -> None:
    redis = FakeRedis()
    app = service(redis)
    activate(app)

    def fail(*args, **kwargs):
        raise RuntimeError("bad trend")

    monkeypatch.setattr("finance_analysis.market_stream.service.calculate_ma_trend", fail)
    await app._handle_event(candle_event(bar(0, confirmed=True, received=61), 2))
    assert len(app.bars_1m["AAPL.US"]) == 1
    assert len(await app.repository.get_recent_bars("AAPL.US", 10)) == 1
    assert not app.stop_event.is_set()


class FailingTrendRepository(RealtimeStateRepository):
    async def write_trend_state(self, trend) -> None:
        raise RuntimeError("redis unavailable")


class FailingPatternRepository(RealtimeStateRepository):
    async def write_pattern_state(self, pattern) -> None:
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_trend_redis_failure_is_pending_and_recovers() -> None:
    redis = FakeRedis()
    repository = FailingTrendRepository(redis)
    app = service(redis, repository)
    activate(app)
    await app._handle_event(candle_event(bar(0, confirmed=True, received=61), 2))
    assert app.redis_degraded
    assert "AAPL.US" in app.pending_trends
    assert await app._flush_pending_redis()
    assert "AAPL.US" not in app.pending_trends
    assert await app.repository.get_trend_state("AAPL.US") is not None


@pytest.mark.asyncio
async def test_pattern_redis_failure_is_pending_and_recovers_without_stopping_stream() -> None:
    redis = FakeRedis()
    repository = FailingPatternRepository(redis)
    app = service(redis, repository)
    activate(app)

    await app._handle_event(candle_event(bar(0, confirmed=True, received=61), 2))

    assert app.redis_degraded
    assert "AAPL.US" in app.pending_patterns
    assert len(app.bars_1m["AAPL.US"]) == 1
    assert await app._flush_pending_redis()
    assert "AAPL.US" not in app.pending_patterns
    assert await app.repository.get_pattern_state("AAPL.US") is not None


@pytest.mark.asyncio
async def test_pattern_calculation_failure_does_not_stop_event_processing(monkeypatch) -> None:
    redis = FakeRedis()
    app = service(redis)
    activate(app)

    def fail(*args, **kwargs):
        raise RuntimeError("bad pattern")

    monkeypatch.setattr("finance_analysis.market_stream.service.calculate_pattern_state", fail)
    await app._handle_event(candle_event(bar(0, confirmed=True, received=61), 2))

    assert len(app.bars_1m["AAPL.US"]) == 1
    assert await app.repository.get_trend_state("AAPL.US") is not None
    assert not app.stop_event.is_set()


@pytest.mark.asyncio
async def test_quote_reference_merge_does_not_replace_newer_push_price() -> None:
    app = service()
    set_warming(app, connection=2)

    await app._handle_event(quote_event("101", 10, 2))
    push_time = app.quotes["AAPL.US"].event_time
    await app._handle_event(quote_reference_event("100", 2))

    quote = app.quotes["AAPL.US"]
    assert quote.last_price == Decimal("101")
    assert quote.pre_close == Decimal("100")
    assert quote.event_time == push_time


@pytest.mark.asyncio
async def test_previous_regular_close_replaces_stale_cross_day_quote_reference() -> None:
    app = service()
    state = set_warming(app, connection=2)
    state.status = SymbolStatus.ACTIVE
    state.quote_subscribed = True
    app._remember_regular_session_closes("AAPL.US", "US", [bar(389, close="30.54")])

    next_session = datetime(2026, 6, 29, 13, 25, tzinfo=timezone.utc)
    await app._handle_event(quote_event("31.23", 10, 2, received_at=next_session, pre_close="25.51"))

    quote = app.quotes["AAPL.US"]
    assert quote.pre_close == Decimal("30.54")
    assert float((quote.last_price - quote.pre_close) / quote.pre_close * Decimal("100")) == pytest.approx(
        2.259332,
        abs=0.000001,
    )


@pytest.mark.asyncio
async def test_same_session_quote_keeps_provider_previous_close() -> None:
    app = service()
    state = set_warming(app, connection=2)
    state.status = SymbolStatus.ACTIVE
    state.quote_subscribed = True
    app._remember_regular_session_closes("AAPL.US", "US", [bar(389, close="30.54")])

    same_session = datetime(2026, 6, 26, 20, 5, tzinfo=timezone.utc)
    await app._handle_event(quote_event("30.54", 10, 2, received_at=same_session, pre_close="28.00"))

    assert app.quotes["AAPL.US"].pre_close == Decimal("28.00")


@pytest.mark.asyncio
async def test_remembered_close_repairs_quote_that_arrived_before_warmup() -> None:
    app = service()
    state = set_warming(app, connection=2)
    state.status = SymbolStatus.ACTIVE
    state.quote_subscribed = True
    next_session = datetime(2026, 6, 29, 13, 25, tzinfo=timezone.utc)
    await app._handle_event(quote_event("31.23", 10, 2, received_at=next_session, pre_close="25.51"))

    app._remember_regular_session_closes("AAPL.US", "US", [bar(389, close="30.54")])

    assert app.quotes["AAPL.US"].pre_close == Decimal("30.54")
    assert app.pending_quotes["AAPL.US"].pre_close == Decimal("30.54")


@pytest.mark.asyncio
async def test_quote_reference_is_refreshed_when_market_date_changes() -> None:
    app = service()
    state = set_warming(app)
    state.status = SymbolStatus.ACTIVE
    state.quote_subscribed = True
    app.quote_reference_dates[state.symbol] = date(2026, 6, 25)
    requested = []

    async def refresh_quotes(symbols):
        requested.append(set(symbols))
        return set(symbols)

    app.manager.refresh_quotes = refresh_quotes
    now = datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc)
    state.last_quote_at = now

    assert await app._refresh_quote_references_once(now=now) == {"AAPL.US"}
    assert requested == [{"AAPL.US"}]
    assert app.quote_reference_dates["AAPL.US"] == date(2026, 6, 26)

    assert await app._refresh_quote_references_once(now=now + timedelta(seconds=5)) == set()
    assert requested == [{"AAPL.US"}]


@pytest.mark.asyncio
async def test_warmup_uses_complete_market_cache_before_history() -> None:
    app = service()
    now = datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc)
    cached_bars = [bar(index) for index in range(30)]
    await app.repository.upsert_bars("AAPL.US", cached_bars)

    class FailingHistory:
        async def fetch(self, symbol, market_type, count):
            raise AssertionError("history should not be called")

    app.history_loader = FailingHistory()
    assert app._cache_has_current_session(cached_bars, "US", now=now)


@pytest.mark.asyncio
async def test_incomplete_market_cache_falls_back_to_history() -> None:
    app = service()
    calls = []

    class History:
        async def fetch(self, symbol, market_type, count):
            calls.append((symbol, market_type, count))
            return [bar(1)]

    app.history_loader = History()
    result = await app._load_warmup("AAPL.US", "US", 1, 1)
    assert calls == [("AAPL.US", "US", 420)]
    assert len(result.historical) == 1


@pytest.mark.asyncio
async def test_warmup_concurrency_is_limited() -> None:
    app = service()
    app.warmup_semaphore = asyncio.Semaphore(2)
    current = 0
    maximum = 0

    class History:
        async def fetch(self, symbol, market_type, count):
            nonlocal current, maximum
            current += 1
            maximum = max(maximum, current)
            await asyncio.sleep(0.02)
            current -= 1
            return []

    app.history_loader = History()
    await asyncio.gather(*(app._load_warmup(f"S{i}.US", "US", 1, 1) for i in range(6)))
    assert maximum == 2


@pytest.mark.asyncio
async def test_reconnect_cancellation_releases_semaphore_and_cleans_old_buffer() -> None:
    app = service()
    app.warmup_semaphore = asyncio.Semaphore(1)
    started: list[int] = []
    cancelled: list[int] = []
    gate = asyncio.Event()

    class History:
        async def fetch(self, symbol, market_type, count):
            connection = app.manager.connection_generation
            started.append(connection)
            try:
                await gate.wait()
            except asyncio.CancelledError:
                cancelled.append(connection)
                raise
            return []

    app.history_loader = History()
    app.manager.desired_loader = None
    app.manager.desired_targets = {"AAPL.US": SubscriptionTarget("AAPL.US", "US")}
    await app.manager.start()
    while len(started) < 1:
        await asyncio.sleep(0.005)
    old_connection = started[0]
    state = app.manager.symbol_states["AAPL.US"]
    old_key = WarmupTaskKey("AAPL.US", state.generation, old_connection)
    app.warming_buffers[old_key] = {bar(0).identity: bar(0)}

    await app.manager.reconnect()
    while len(started) < 2:
        await asyncio.sleep(0.005)
    assert cancelled == [old_connection]
    assert old_key not in app.warming_buffers
    assert started[1] != old_connection
    gate.set()
    await app.manager.stop()

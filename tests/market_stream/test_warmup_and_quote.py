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
from finance_analysis.stocks.markets import MarketType
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
    symbol: str = "AAPL.US",
) -> MarketEvent:
    received_at = received_at or BASE + timedelta(seconds=sequence)
    payload = {"last_price": price, "sequence": sequence, "trade_session": "Intraday"}
    if pre_close is not None:
        payload["pre_close"] = pre_close
    return MarketEvent(
        "quote",
        symbol,
        received_at,
        received_at,
        sequence,
        "Intraday",
        payload,
        connection_generation,
    )


def quote_snapshot_event(
    *,
    symbol: str = "AAPL.US",
    received_at: datetime = BASE,
    connection_generation: int = 2,
    sequence: int = 1,
    last_price: str = "101",
    pre_close: str = "100",
    open_price: str = "100.5",
    high: str = "102",
    low: str = "99.5",
) -> MarketEvent:
    return MarketEvent(
        "quote_snapshot",
        symbol,
        received_at,
        received_at,
        sequence,
        "Intraday",
        {
            "last_price": last_price,
            "pre_close": pre_close,
            "open": open_price,
            "high": high,
            "low": low,
            "volume": 100,
            "turnover": "10100",
            "sequence": sequence,
            "trade_session": "Intraday",
        },
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


def set_warming(
    app: MarketStreamService,
    *,
    generation: int = 3,
    connection: int = 2,
    symbol: str = "AAPL.US",
    market_type: MarketType = "US",
) -> SymbolRuntimeState:
    target = SubscriptionTarget(symbol, market_type)
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
        trading_date=date(2026, 6, 26),
    )
    assert quote.merge(
        {"last_price": "101", "sequence": 3},
        event_time=BASE + timedelta(seconds=1),
        received_at=BASE + timedelta(seconds=2),
        trading_date=date(2026, 6, 26),
    )
    assert quote.open == Decimal("98")
    assert quote.volume == 10
    assert not quote.merge(
        {"last_price": "1", "sequence": 1},
        event_time=BASE,
        received_at=BASE,
        trading_date=date(2026, 6, 26),
    )
    assert quote.last_price == Decimal("101")


@pytest.mark.asyncio
async def test_cross_day_partial_quote_clears_previous_ohlc_before_full_snapshot() -> None:
    app = service()
    state = set_warming(app, symbol="600519.SH", market_type="CN")
    state.status = SymbolStatus.ACTIVE
    day_one = datetime(2026, 6, 25, 1, 30, tzinfo=timezone.utc)
    day_two = datetime(2026, 6, 26, 1, 30, tzinfo=timezone.utc)

    await app._handle_event(
        quote_snapshot_event(
            symbol="600519.SH",
            received_at=day_one,
            sequence=100,
            last_price="105",
            pre_close="99",
            open_price="100",
            high="106",
            low="98",
        )
    )
    await app._handle_event(quote_event("101", 1, 2, received_at=day_two, symbol="600519.SH"))

    quote = app.quotes["600519.SH"]
    assert quote.trading_date == date(2026, 6, 26)
    assert quote.last_price == Decimal("101")
    assert quote.open is None
    assert quote.high is None
    assert quote.low is None
    assert quote.pre_close is None

    await app._handle_event(
        quote_snapshot_event(
            symbol="600519.SH",
            received_at=day_two,
            sequence=2,
            last_price="102",
            pre_close="105",
            open_price="101",
            high="103",
            low="100.5",
        )
    )

    assert quote.open == Decimal("101")
    assert quote.high == Decimal("103")
    assert quote.low == Decimal("100.5")
    assert quote.pre_close == Decimal("105")
    assert quote.last_price - quote.pre_close == Decimal("-3")
    assert app.quote_snapshot_dates["600519.SH"] == date(2026, 6, 26)


@pytest.mark.asyncio
async def test_delayed_previous_day_quote_cannot_roll_back_current_state() -> None:
    app = service()
    activate(app)
    day_one = datetime(2026, 6, 26, 13, 30, tzinfo=timezone.utc)
    day_two = datetime(2026, 6, 29, 13, 30, tzinfo=timezone.utc)
    await app._handle_event(quote_snapshot_event(received_at=day_two, sequence=2))

    await app._handle_event(quote_event("1", 999, 2, received_at=day_one))

    quote = app.quotes["AAPL.US"]
    assert quote.trading_date == date(2026, 6, 29)
    assert quote.last_price == Decimal("101")
    assert quote.sequence == 2


@pytest.mark.asyncio
async def test_cn_lunch_reconnect_style_quote_keeps_same_day_open() -> None:
    app = service()
    state = set_warming(app, symbol="600519.SH", market_type="CN")
    state.status = SymbolStatus.ACTIVE
    morning = datetime(2026, 6, 26, 2, 0, tzinfo=timezone.utc)
    afternoon = datetime(2026, 6, 26, 5, 0, tzinfo=timezone.utc)
    await app._handle_event(
        quote_snapshot_event(
            symbol="600519.SH",
            received_at=morning,
            open_price="1500",
            last_price="1510",
            pre_close="1490",
            high="1520",
            low="1488",
        )
    )

    await app._handle_event(quote_event("1515", 2, 2, received_at=afternoon, symbol="600519.SH"))

    quote = app.quotes["600519.SH"]
    assert quote.trading_date == date(2026, 6, 26)
    assert quote.open == Decimal("1500")
    assert quote.last_price == Decimal("1515")


@pytest.mark.asyncio
async def test_us_utc_date_change_does_not_reset_same_local_trading_date() -> None:
    app = service()
    activate(app)
    before_utc_midnight = datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)
    after_utc_midnight = datetime(2026, 7, 2, 1, 0, tzinfo=timezone.utc)
    await app._handle_event(
        quote_snapshot_event(
            received_at=before_utc_midnight,
            open_price="200",
            last_price="202",
            pre_close="199",
            high="203",
            low="198",
        )
    )

    await app._handle_event(quote_event("201", 2, 2, received_at=after_utc_midnight))

    quote = app.quotes["AAPL.US"]
    assert quote.trading_date == date(2026, 7, 1)
    assert quote.open == Decimal("200")


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
async def test_full_quote_snapshot_is_refreshed_and_marked_after_merge_each_market_date() -> None:
    app = service()
    state = set_warming(app)
    state.status = SymbolStatus.ACTIVE
    state.quote_subscribed = True
    app.quote_snapshot_dates[state.symbol] = date(2026, 6, 26)
    requested = []

    async def refresh_quotes(symbols, *, reference_only=True):
        requested.append((set(symbols), reference_only))
        return set(symbols)

    app.manager.refresh_quotes = refresh_quotes
    day_two = datetime(2026, 6, 29, 14, 0, tzinfo=timezone.utc)
    state.last_quote_at = day_two

    assert await app._refresh_quote_snapshots_once(now=day_two) == {"AAPL.US"}
    assert requested == [({"AAPL.US"}, False)]
    assert app.quote_snapshot_dates["AAPL.US"] == date(2026, 6, 26)

    incomplete = quote_snapshot_event(received_at=day_two, sequence=1)
    incomplete.payload.pop("open")
    await app._handle_event(incomplete)
    assert app.quote_snapshot_dates["AAPL.US"] == date(2026, 6, 26)

    await app._handle_event(quote_snapshot_event(received_at=day_two, sequence=2))
    assert app.quote_snapshot_dates["AAPL.US"] == date(2026, 6, 29)
    assert await app._refresh_quote_snapshots_once(now=day_two + timedelta(seconds=5)) == set()

    day_three = datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc)
    state.last_quote_at = day_three
    assert await app._refresh_quote_snapshots_once(now=day_three) == {"AAPL.US"}
    assert requested == [({"AAPL.US"}, False), ({"AAPL.US"}, False)]
    await app._handle_event(quote_snapshot_event(received_at=day_three, sequence=1))
    assert app.quote_snapshot_dates["AAPL.US"] == date(2026, 6, 30)


@pytest.mark.asyncio
async def test_failed_cross_day_full_snapshot_is_retried() -> None:
    app = service()
    state = set_warming(app)
    state.status = SymbolStatus.ACTIVE
    state.quote_subscribed = True
    app.quote_snapshot_dates[state.symbol] = date(2026, 6, 26)
    day_two = datetime(2026, 6, 29, 14, 0, tzinfo=timezone.utc)
    state.last_quote_at = day_two
    attempts = 0

    async def refresh_quotes(symbols, *, reference_only=True):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("snapshot unavailable")
        return set(symbols)

    app.manager.refresh_quotes = refresh_quotes

    with pytest.raises(RuntimeError, match="snapshot unavailable"):
        await app._refresh_quote_snapshots_once(now=day_two)
    assert await app._refresh_quote_snapshots_once(now=day_two + timedelta(seconds=5)) == set()
    assert await app._refresh_quote_snapshots_once(now=day_two + timedelta(seconds=61)) == {"AAPL.US"}
    assert attempts == 2
    assert app.quote_snapshot_dates["AAPL.US"] == date(2026, 6, 26)

    # Returning the symbol is not completion; without a valid merged event the
    # next retry window still requests another full snapshot.
    assert await app._refresh_quote_snapshots_once(now=day_two + timedelta(seconds=122)) == {"AAPL.US"}
    assert attempts == 3


@pytest.mark.asyncio
async def test_warmup_restores_previous_close_before_filtering_to_current_session() -> None:
    app = service()
    state = set_warming(app, symbol="600519.SH", market_type="CN")
    day_two_quote = datetime(2026, 6, 26, 1, 35, tzinfo=timezone.utc)
    await app._handle_event(
        quote_event(
            "103",
            1,
            2,
            received_at=day_two_quote,
            pre_close="90",
            symbol="600519.SH",
        )
    )
    day_one_close = CandleState(
        symbol="600519.SH",
        bar_time=datetime(2026, 6, 25, 6, 59, tzinfo=timezone.utc),
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=100,
        turnover=Decimal("10000"),
        trade_session="Intraday",
        confirmed=True,
        received_at=datetime(2026, 6, 25, 7, 0, tzinfo=timezone.utc),
    )
    day_two_bar = CandleState(
        symbol="600519.SH",
        bar_time=datetime(2026, 6, 26, 1, 30, tzinfo=timezone.utc),
        open=Decimal("101"),
        high=Decimal("104"),
        low=Decimal("101"),
        close=Decimal("103"),
        volume=100,
        turnover=Decimal("10300"),
        trade_session="Intraday",
        confirmed=True,
        received_at=datetime(2026, 6, 26, 1, 31, tzinfo=timezone.utc),
    )
    finalized = []

    assert await app._apply_warmup(
        state,
        2,
        WarmupResult("600519.SH", "CN", [], [day_one_close, day_two_bar], 0.1),
        None,
        lambda count, error, trading_date: finalized.append((count, error, trading_date)),
    )

    assert app.quotes["600519.SH"].pre_close == Decimal("100")
    assert list(app.bars_1m["600519.SH"]) == [day_two_bar]
    assert finalized == [(1, None, date(2026, 6, 26))]


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

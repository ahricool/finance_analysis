from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from tests.market_stream.fakes import FakeRedis


def candle(minute: int, close: str = "10", *, received_offset: int = 0) -> CandleState:
    when = datetime(2026, 6, 26, 14, minute, tzinfo=timezone.utc)
    return CandleState(
        symbol="AAPL.US",
        bar_time=when,
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal(close),
        volume=100 + minute,
        turnover=Decimal("1000.5"),
        trade_session="Intraday",
        confirmed=True,
        received_at=when + timedelta(seconds=received_offset),
    )


@pytest.mark.asyncio
async def test_quote_hash_round_trip_and_ttl() -> None:
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    quote = QuoteState(symbol="AAPL.US")
    now = datetime.now(timezone.utc)
    quote.merge(
        {"last_price": Decimal("201.25"), "volume": 10, "turnover": Decimal("9.5")},
        event_time=now,
        received_at=now,
    )
    await repo.write_quote(quote)

    restored = await repo.get_quote("AAPL.US")
    assert restored is not None
    assert restored.last_price == Decimal("201.25")
    assert restored.volume == 10
    assert await redis.ttl(keys.quote_key("AAPL.US")) == 2 * 86400


@pytest.mark.asyncio
async def test_current_candle_overwrites_and_serializes_decimal_datetime() -> None:
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    await repo.write_current_candle(candle(1, "10"))
    await repo.write_current_candle(candle(2, "11"))

    restored = await repo.get_current_candle("AAPL.US")
    assert restored is not None
    assert restored.bar_time.minute == 2
    assert restored.close == Decimal("11")
    assert restored.received_at.tzinfo is not None


@pytest.mark.asyncio
async def test_bars_sorted_replaced_trimmed_and_queried() -> None:
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis, bar_limit=3)
    await repo.upsert_bars("AAPL.US", [candle(2), candle(0), candle(1)])
    await repo.upsert_bars("AAPL.US", [candle(1, "11", received_offset=20), candle(3)])

    bars = await repo.get_recent_bars("AAPL.US", 10)
    assert [bar.bar_time.minute for bar in bars] == [1, 2, 3]
    assert bars[0].close == Decimal("11")
    assert len(redis.zsets[keys.bars_index_key("AAPL.US")]) == 3
    ranged = await repo.get_bars_by_time("AAPL.US", candle(2).bar_time, candle(3).bar_time)
    assert [bar.bar_time.minute for bar in ranged] == [2, 3]
    assert await redis.ttl(keys.bars_data_key("AAPL.US")) == 3 * 86400


@pytest.mark.asyncio
async def test_same_minute_different_trade_sessions_have_distinct_stable_members() -> None:
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    regular = candle(1)
    extended = candle(1)
    extended.trade_session = "Post"
    await repo.upsert_bars("AAPL.US", [regular, extended])
    assert len(await repo.get_recent_bars("AAPL.US", 10)) == 2
    assert len(redis.zsets[keys.bars_index_key("AAPL.US")]) == 2


@pytest.mark.asyncio
async def test_batch_write_uses_one_pipeline_and_removed_cache_ttl() -> None:
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    quote = QuoteState(symbol="AAPL.US", last_price=Decimal("1"))
    await repo.write_batch({"AAPL.US": quote}, {"AAPL.US": candle(1)})
    assert redis.pipeline_executes == 1
    await repo.expire_symbol_cache("AAPL.US")
    assert await redis.ttl(keys.bars_index_key("AAPL.US")) == 7200
    assert await redis.ttl(keys.subscription_key("AAPL.US")) == 7200


@pytest.mark.asyncio
async def test_heartbeat_has_ttl() -> None:
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    await repo.write_heartbeat({"status": "READY"}, ttl_seconds=30)
    assert redis.hashes[keys.STREAMER_HEARTBEAT_KEY]["status"] == "READY"
    assert await redis.ttl(keys.STREAMER_HEARTBEAT_KEY) == 30

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.integrations.market_data.realtime_state.data_source import (
    RealtimeMarketDataSource,
    RealtimeReadPolicy,
)
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.integrations.market_data.realtime_types import RealtimeSource
from finance_analysis.market_stream.config import market_timezone
from tests.market_stream.fakes import FakeRedis


async def _seed_health(
    repo: RealtimeStateRepository,
    symbol: str,
    market_type: str,
    now: datetime,
    *,
    subscription_status: str = "ACTIVE",
    heartbeat_at: datetime | None = None,
) -> None:
    await repo.write_heartbeat(
        {"status": "READY", "updated_at": heartbeat_at or now},
        ttl_seconds=30,
    )
    await repo.write_subscription(
        symbol,
        {"status": subscription_status, "market_type": market_type},
        ttl_seconds=60,
    )


def _quote(symbol: str, now: datetime, *, received_at: datetime | None = None) -> QuoteState:
    quote = QuoteState(symbol=symbol)
    quote.merge(
        {
            "last_price": Decimal("101.25"),
            "pre_close": Decimal("100"),
            "open": Decimal("100.5"),
            "high": Decimal("102"),
            "low": Decimal("99.5"),
            "volume": 1000,
            "turnover": Decimal("101250"),
        },
        event_time=now,
        received_at=received_at or now,
    )
    return quote


def _bars(symbol: str, now: datetime, market_type: str, count: int = 15) -> list[CandleState]:
    market_tz = market_timezone(market_type)  # type: ignore[arg-type]
    local = now.astimezone(market_tz)
    last_completed = local.replace(second=0, microsecond=0) - timedelta(minutes=1)
    result = []
    for offset in reversed(range(count)):
        bar_time = (last_completed - timedelta(minutes=offset)).astimezone(timezone.utc)
        result.append(
            CandleState(
                symbol=symbol,
                bar_time=bar_time,
                open=Decimal("100"),
                high=Decimal("102"),
                low=Decimal("99"),
                close=Decimal("101"),
                volume=100,
                turnover=Decimal("10100"),
                trade_session="Intraday",
                confirmed=True,
                received_at=bar_time + timedelta(minutes=1),
            )
        )
    return result


@pytest.mark.asyncio
async def test_valid_quote_is_converted_to_existing_model() -> None:
    now = datetime(2026, 6, 26, 14, 0, 10, tzinfo=timezone.utc)
    repo = RealtimeStateRepository(FakeRedis())
    await _seed_health(repo, "AAPL.US", "US", now)
    await repo.write_quote(_quote("AAPL.US", now))

    quote = await RealtimeMarketDataSource(repo).get_quote("AAPL", market_type="US", now=now)

    assert quote is not None
    assert quote.code == "AAPL"
    assert quote.source is RealtimeSource.MARKET_STREAMER
    assert quote.price == 101.25
    assert quote.change_pct == 1.25


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "heartbeat_at", "quote_at"),
    [
        ("stale_heartbeat", timedelta(seconds=-20), timedelta()),
        ("stale_quote", timedelta(), timedelta(seconds=-31)),
    ],
)
async def test_stale_realtime_state_returns_fallback_reason(reason, heartbeat_at, quote_at) -> None:
    now = datetime(2026, 6, 26, 14, 0, 10, tzinfo=timezone.utc)
    repo = RealtimeStateRepository(FakeRedis())
    await _seed_health(repo, "AAPL.US", "US", now, heartbeat_at=now + heartbeat_at)
    await repo.write_quote(_quote("AAPL.US", now, received_at=now + quote_at))

    lookup = await RealtimeMarketDataSource(repo).get_quote_lookup("AAPL", market_type="US", now=now)

    assert lookup.data is None
    assert lookup.fallback_reason == reason


@pytest.mark.asyncio
async def test_warming_allows_quote_but_not_incomplete_history() -> None:
    now = datetime(2026, 6, 26, 14, 0, 10, tzinfo=timezone.utc)
    repo = RealtimeStateRepository(FakeRedis())
    await _seed_health(repo, "AAPL.US", "US", now, subscription_status="WARMING")
    await repo.write_quote(_quote("AAPL.US", now))
    await repo.upsert_bars("AAPL.US", _bars("AAPL.US", now, "US"))
    source = RealtimeMarketDataSource(repo)

    quote = await source.get_quote("AAPL", market_type="US", now=now)
    bars = await source.get_recent_bars("AAPL", 15, market_type="US", minimum_count=15, now=now)

    assert quote is not None
    assert bars is None


@pytest.mark.asyncio
async def test_bar_count_and_current_candle_merge_are_validated() -> None:
    now = datetime(2026, 6, 26, 10, 0, 20, tzinfo=ZoneInfo("America/New_York"))
    repo = RealtimeStateRepository(FakeRedis())
    await _seed_health(repo, "AAPL.US", "US", now)
    historical = _bars("AAPL.US", now, "US")
    await repo.upsert_bars("AAPL.US", historical)
    current_time = now.replace(second=0, microsecond=0).astimezone(timezone.utc)
    old_current = CandleState(
        symbol="AAPL.US",
        bar_time=current_time,
        open=Decimal("101"),
        high=Decimal("103"),
        low=Decimal("100"),
        close=Decimal("102"),
        volume=120,
        turnover=Decimal("12240"),
        trade_session="Intraday",
        confirmed=False,
        received_at=current_time + timedelta(seconds=10),
    )
    await repo.upsert_bars("AAPL.US", [old_current])
    current = CandleState(
        symbol="AAPL.US",
        bar_time=current_time,
        open=Decimal("101"),
        high=Decimal("104"),
        low=Decimal("100"),
        close=Decimal("103"),
        volume=150,
        turnover=Decimal("15450"),
        trade_session="Intraday",
        confirmed=False,
        received_at=current_time + timedelta(seconds=20),
    )
    await repo.write_current_candle(current)
    source = RealtimeMarketDataSource(repo)

    insufficient = await source.get_recent_bars(
        "AAPL", 20, market_type="US", minimum_count=20, now=now
    )
    confirmed_only = await source.get_recent_bars(
        "AAPL", 20, market_type="US", minimum_count=15, now=now
    )
    bars = await source.get_recent_bars(
        "AAPL",
        20,
        market_type="US",
        minimum_count=15,
        include_incomplete=True,
        now=now,
    )

    assert insufficient is None
    assert confirmed_only is not None
    assert confirmed_only[-1]["timestamp"].endswith("09:59:00-04:00")
    assert bars is not None
    timestamps = [bar["timestamp"] for bar in bars]
    assert len(timestamps) == len(set(timestamps))
    assert bars[-1]["close"] == 103.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("market_type", "symbol", "now", "timezone_name"),
    [
        ("CN", "600519.SH", datetime(2026, 6, 26, 2, 0, 10, tzinfo=timezone.utc), "Asia/Shanghai"),
        ("HK", "0700.HK", datetime(2026, 6, 26, 2, 0, 10, tzinfo=timezone.utc), "Asia/Hong_Kong"),
        ("US", "AAPL.US", datetime(2026, 6, 26, 14, 0, 10, tzinfo=timezone.utc), "America/New_York"),
    ],
)
async def test_bars_use_each_market_timezone(market_type, symbol, now, timezone_name) -> None:
    repo = RealtimeStateRepository(FakeRedis())
    await _seed_health(repo, symbol, market_type, now)
    await repo.upsert_bars(symbol, _bars(symbol, now, market_type))

    bars = await RealtimeMarketDataSource(repo).get_recent_bars(
        symbol,
        15,
        market_type=market_type,
        minimum_count=15,
        now=now,
    )

    assert bars is not None
    parsed = datetime.fromisoformat(bars[-1]["timestamp"])
    assert parsed.astimezone(ZoneInfo(timezone_name)).date() == now.astimezone(ZoneInfo(timezone_name)).date()


@pytest.mark.asyncio
async def test_redis_failure_is_a_cache_miss() -> None:
    class FailingRepository:
        async def get_heartbeat(self):
            raise RuntimeError("redis unavailable")

    source = RealtimeMarketDataSource(FailingRepository())  # type: ignore[arg-type]
    now = datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc)

    lookup = await source.get_quote_lookup("AAPL", market_type="US", now=now)

    assert lookup.data is None
    assert lookup.fallback_reason == "redis_error"

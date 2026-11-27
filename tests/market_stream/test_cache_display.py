from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from finance_analysis.integrations.market_data.realtime_state.cached import display_quote
from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.interfaces.api.v1.endpoints import market_data
from tests.market_stream.fakes import FakeRedis

NOW = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)


def test_cache_display_keeps_market_time_and_rejects_future_and_wrong_date():
    state = QuoteState(
        "600519.SH",
        trading_date=NOW.date(),
        last_price=Decimal("10"),
        pre_close=Decimal("9"),
        event_time=NOW,
        received_at=NOW,
        source="fuyao",
        timestamp_kind="batch",
    )
    quote = display_quote(state, "CN", NOW)
    assert quote.quote_time == NOW and quote.provider == "fuyao" and quote.change_amount == 1
    assert display_quote(replace(state, event_time=NOW + timedelta(seconds=10)), "CN", NOW) is None
    assert display_quote(replace(state, trading_date=(NOW - timedelta(days=1)).date()), "CN", NOW) is None
    assert display_quote(replace(state, event_time=None), "CN", NOW) is None
    assert display_quote(replace(state, timestamp_kind="received"), "CN", NOW) is None


@pytest.mark.asyncio
async def test_cn_health_and_stale_event_time_are_independent_of_longbridge():
    from finance_analysis.integrations.market_data.realtime_state.data_source import RealtimeMarketDataSource
    repo = RealtimeStateRepository(FakeRedis())
    await repo.write_heartbeat({"status": "DISCONNECTED", "cn_status": "READY", "updated_at": NOW})
    await repo.write_subscription("600519.SH", {"status": "ACTIVE", "market_type": "CN"}, ttl_seconds=60)
    quote = QuoteState("600519.SH", trading_date=NOW.date(), last_price=Decimal("10"),
                       event_time=NOW, received_at=NOW, source="fuyao", timestamp_kind="batch")
    await repo.write_quote(quote)
    source = RealtimeMarketDataSource(repo)
    assert await source.get_quote("600519.SH", market_type="CN", now=NOW) is not None
    quote.event_time -= timedelta(seconds=31)
    await repo.write_quote(quote)
    assert await source.get_quote("600519.SH", market_type="CN", now=NOW) is None


@pytest.mark.asyncio
async def test_switching_cn_source_discards_legacy_native_minutes():
    from finance_analysis.market_stream.service import MarketStreamService
    from finance_analysis.market_stream.config import MarketStreamConfig
    from finance_analysis.market_stream.symbol_state import SubscriptionTarget
    from tests.market_stream.test_realtime_repository import candle
    repo = RealtimeStateRepository(FakeRedis())
    bar = replace(candle(0), symbol="600519.SH", bar_time=NOW, received_at=NOW)
    await repo.upsert_bars(bar.symbol, [bar])
    app = MarketStreamService(config=MarketStreamConfig(redis_url="redis://unused"), repository=repo)
    await app.cn_feed.reconcile({bar.symbol: SubscriptionTarget(bar.symbol, "CN")})
    assert await repo.get_recent_bars(bar.symbol, 20) == []


@pytest.mark.asyncio
async def test_day_switch_cannot_reintroduce_yesterday_bars_and_events_are_immutable():
    from tests.market_stream.test_realtime_repository import candle, pattern

    repository = RealtimeStateRepository(FakeRedis())
    first = candle(0)
    today = replace(
        first, bar_time=first.bar_time + timedelta(days=3), received_at=first.received_at + timedelta(days=3)
    )
    await repository.upsert_bars(first.symbol, [first])
    await repository.upsert_bars(first.symbol, [today])
    await repository.upsert_bars(first.symbol, [first])
    assert await repository.get_recent_bars(first.symbol, 20) == [today]
    value = pattern()
    await repository.record_pattern_event(value, NOW)
    changed = replace(value, signal=replace(value.signal, quality_score=10))
    await repository.record_pattern_event(changed, NOW + timedelta(minutes=1))
    events = await repository.get_pattern_events(value.symbol, value.trading_date)
    assert len(events) == 1 and events[0]["quality_score"] == value.signal.quality_score
    assert events[0]["observed_at"] == "2026-10-21T02:00:00.000Z"


@pytest.mark.asyncio
async def test_intraday_is_owned_cache_only_and_filters_previous_session(monkeypatch):
    from tests.market_stream.test_realtime_repository import candle

    repo = RealtimeStateRepository(FakeRedis())
    now = datetime(2026, 6, 26, 14, 5, tzinfo=timezone.utc)
    await repo.upsert_bars("AAPL.US", [candle(0), candle(1)])
    monkeypatch.setattr(market_data, "get_effective_uid", lambda request: 7)
    monkeypatch.setattr(market_data, "utc_now", lambda: now)
    monkeypatch.setattr(
        market_data, "_load_tracked_stocks", lambda uid, market: [market_data.TrackedStock("AAPL", "US", "AAPL.US")]
    )
    monkeypatch.setattr(market_data.RealtimeStateRepository, "from_url", lambda url: repo)
    monkeypatch.setattr(
        market_data, "MarketDataService", lambda: (_ for _ in ()).throw(AssertionError("external request"))
    )
    value = await market_data.intraday_bars("AAPL.US", SimpleNamespace())
    assert value["reset"] and len(value["items"]) == 2
    assert value["trading_date"] == now.date()
    cursor = candle(1).bar_time
    version = value["history_version"]
    for token in [None, version]:
        value = await market_data.intraday_bars("AAPL.US", SimpleNamespace(), since=cursor, history_version=token)
        assert not value["reset"] and not value["full_snapshot"] and len(value["items"]) == 1

    # A correction before the cursor changes OHLC without changing the number of minutes.
    revised = replace(candle(0), close=Decimal("11"), received_at=now)
    await repo.upsert_bars("AAPL.US", [revised, candle(2)])
    value = await market_data.intraday_bars("AAPL.US", SimpleNamespace(), since=cursor, history_version=version)
    assert value["full_snapshot"] and len(value["items"]) == 3 and value["items"][0]["close"] == 11
    version = value["history_version"]
    await repo.upsert_bars("AAPL.US", [candle(3)])
    value = await market_data.intraday_bars("AAPL.US", SimpleNamespace(), since=candle(2).bar_time, history_version=version)
    assert not value["full_snapshot"] and len(value["items"]) == 2
    # A newly restored opening candle before the latest cursor also requires a replacement snapshot.
    earlier = replace(candle(0), bar_time=candle(0).bar_time - timedelta(minutes=1))
    await repo.upsert_bars("AAPL.US", [earlier])
    value = await market_data.intraday_bars("AAPL.US", SimpleNamespace(), since=candle(3).bar_time,
                                            history_version=value["history_version"])
    assert value["full_snapshot"] and len(value["items"]) == 5


@pytest.mark.asyncio
async def test_intraday_does_not_expose_other_users_collected_symbols(monkeypatch):
    from fastapi import HTTPException
    from finance_analysis.portfolio.service import PortfolioService

    monkeypatch.setattr(market_data, "get_effective_uid", lambda request: 7)
    monkeypatch.setattr(market_data, "_load_tracked_stocks", lambda uid, market: [])
    monkeypatch.setattr(PortfolioService, "__init__", lambda self: None)
    monkeypatch.setattr(PortfolioService, "read_snapshot", lambda self, uid, market: ([], []))
    with pytest.raises(HTTPException) as error:
        await market_data.intraday_bars("KO.US", SimpleNamespace())
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_hk_intraday_displays_only_cached_regular_minutes_from_latest_session(monkeypatch):
    from tests.market_stream.test_realtime_repository import candle

    repo = RealtimeStateRepository(FakeRedis())
    symbol = "700.HK"
    now = NOW.replace(hour=7)
    bars = [
        replace(candle(0), symbol=symbol, bar_time=stamp, received_at=stamp)
        for stamp in (now.replace(hour=2), now.replace(hour=4, minute=15), now.replace(hour=6))
    ]
    await repo.upsert_bars(symbol, bars)

    async def require_access(request, code, market):
        assert (code, market) == (symbol, "HK")
        return 7

    monkeypatch.setattr(market_data, "_require_intraday_access", require_access)
    monkeypatch.setattr(market_data, "utc_now", lambda: now)
    monkeypatch.setattr(market_data.RealtimeStateRepository, "from_url", lambda url: repo)
    result = await market_data.intraday_bars("00700.HK", SimpleNamespace(), since=now - timedelta(days=1))
    assert result["market"] == "HK" and result["full_snapshot"] and result["reset"]
    assert [bar["timestamp"] for bar in result["items"]] == [
        int(bars[i].bar_time.timestamp() * 1000) for i in (0, 2)
    ]

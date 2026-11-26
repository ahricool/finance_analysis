from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from longbridge.openapi import TradeSessions

from finance_analysis.integrations.market_data.models import MinuteBarsRequest
from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeProvider
from finance_analysis.integrations.market_data.providers.longbridge.normalizer import normalize_quote_snapshot
from finance_analysis.integrations.market_data.providers.longbridge.streaming import LongbridgeStreamingClient
from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import US_MINUTE_LIMIT, us_minute_cutoff
from finance_analysis.market_stream.session import us_minute_session
from tests.market_stream.fakes import FakeRedis
from tests.market_stream.test_realtime_repository import candle


def at(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def minute(stamp, session="Overnight"):
    return replace(candle(0), bar_time=stamp, received_at=stamp + timedelta(seconds=30), trade_session=session)


@pytest.mark.asyncio
async def test_us_subscription_uses_all_sessions_but_hk_stays_regular():
    calls = []

    class Context:
        async def subscribe_candlesticks(self, symbol, period, sessions):
            calls.append((symbol, sessions))

    client = LongbridgeStreamingClient()
    client.context = Context()
    client.prepared_symbols = {"AAPL.US", "700.HK"}
    await client.subscribe(client.prepared_symbols)
    assert calls == [("700.HK", TradeSessions.Intraday), ("AAPL.US", TradeSessions.All)]


def test_history_paginates_full_extended_window_and_preserves_labels(monkeypatch):
    now = at("2026-11-25T07:00:00-05:00")
    start = now - timedelta(hours=24)
    timeline = [minute(start + timedelta(minutes=i)) for i in range(1440)]
    calls = []

    class Context:
        def history_candlesticks_by_offset(self, symbol, period, adjustment, forward, count, cursor, sessions):
            calls.append(sessions)
            return [SimpleNamespace(timestamp=b.bar_time, open=b.open, high=b.high, low=b.low, close=b.close,
                                    volume=b.volume, turnover=b.turnover, trade_session=b.trade_session)
                    for b in timeline if b.bar_time <= cursor][-count:]

    provider = LongbridgeProvider()
    monkeypatch.setattr(provider, "_get_ctx", lambda: Context())
    monkeypatch.setattr(provider, "is_available_for_request", lambda *args: True)
    result = provider.fetch_minute_bars(MinuteBarsRequest(("AAPL.US",), start, now, include_extended=True))
    assert calls == [TradeSessions.All, TradeSessions.All]
    assert len(result.data["AAPL.US"]) == 1440
    assert result.data["AAPL.US"][0].trade_session == "Overnight"


@pytest.mark.asyncio
async def test_rolling_1440_slots_cross_midnight_and_prune_idle_symbols():
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    now = at("2026-11-25T04:00:00-05:00")
    bars = [minute(now - timedelta(minutes=i)) for i in range(1, 1442)]
    await repo.upsert_bars("AAPL.US", bars)
    actual = await repo.get_recent_bars("AAPL.US", 2000)
    assert len(actual) == US_MINUTE_LIMIT
    assert actual[0].bar_time == us_minute_cutoff(now)
    assert actual[-1].bar_time == now - timedelta(minutes=1)
    assert actual[0].bar_time.astimezone(ZoneInfo("America/New_York")).date() < actual[-1].bar_time.astimezone(ZoneInfo("America/New_York")).date()
    assert len(redis.hashes[keys.bars_data_key("AAPL.US")]) == 1440
    previous_revision = (await repo.get_bar_revisions(["AAPL.US"]))["AAPL.US"]
    await repo.prune_us_minutes(["AAPL.US"], now + timedelta(hours=1))
    assert len(await repo.get_recent_bars("AAPL.US", 2000)) == 1380
    assert (await repo.get_bar_revisions(["AAPL.US"]))["AAPL.US"] != previous_revision
    await repo.prune_us_minutes(["AAPL.US"], now + timedelta(days=1))
    assert await repo.get_recent_bars("AAPL.US", 2000) == []


@pytest.mark.parametrize("time,label,expected", [
    ("2026-11-25T02:00:00-05:00", None, "overnight"),
    ("2026-11-25T04:00:00-05:00", None, "pre"),
    ("2026-11-25T09:30:00-05:00", "Intraday", "regular"),
    ("2026-11-27T13:00:00-05:00", None, "post"),  # NYSE early close
    ("2026-11-25T20:00:00-05:00", "Overnight", "overnight"),
    ("2026-06-25T04:00:00-04:00", "Pre", "pre"),
    ("2026-06-25T16:00:00-04:00", "Post", "post"),
])
def test_session_labels_follow_provider_and_exchange_calendar(time, label, expected):
    assert us_minute_session(at(time), label) == expected


def test_quote_snapshot_uses_newest_extended_price_and_regular_reference():
    regular = SimpleNamespace(timestamp=at("2026-06-25T15:59:00-04:00"), last_done="100", prev_close="95")
    regular.pre_market_quote = SimpleNamespace(timestamp=at("2026-06-26T04:01:00-04:00"), last_done="103", prev_close="101")
    regular.post_market_quote = SimpleNamespace(timestamp=at("2026-06-25T17:02:00-04:00"), last_done="102")
    event = normalize_quote_snapshot("AAPL.US", regular, generation=1)
    assert event.trade_session == "Pre"
    assert event.payload["last_price"] == "103"
    assert event.payload["pre_close"] == "100"


@pytest.mark.asyncio
async def test_expired_retry_cannot_recreate_old_redis_history():
    now = at("2026-11-25T04:00:00-05:00")
    repo = RealtimeStateRepository(FakeRedis(), clock=lambda: now)
    old = minute(now - timedelta(hours=25))
    await repo.upsert_bars("AAPL.US", [old])
    assert await repo.get_recent_bars("AAPL.US", 1440) == []
    await repo.write_current_candle(old)
    assert await repo.redis.ttl(keys.current_candle_key("AAPL.US")) == 1


@pytest.mark.asyncio
async def test_us_api_returns_cross_date_sessions_and_expires_cursor_history(monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints import market_data
    from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
    from decimal import Decimal

    now = at("2026-11-25T04:30:00-05:00")
    repo = RealtimeStateRepository(FakeRedis())
    bars = [minute(at(stamp), label) for stamp, label in [
        ("2026-11-24T04:31:00-05:00", "Pre"),
        ("2026-11-24T15:59:00-05:00", "Intraday"),
        ("2026-11-24T18:00:00-05:00", "Post"),
        ("2026-11-25T00:05:00-05:00", "Overnight"),
        ("2026-11-25T04:29:00-05:00", "Pre"),
    ]]
    await repo.upsert_bars("AAPL.US", bars)
    quote = QuoteState("AAPL.US", trading_date=now.date(), last_price=Decimal("10"),
                       trade_session="Pre", event_time=now, received_at=now)
    await repo.write_quote(quote)

    async def access(*args):
        return 7

    monkeypatch.setattr(market_data, "_require_intraday_access", access)
    monkeypatch.setattr(market_data, "utc_now", lambda: now)
    monkeypatch.setattr(market_data.RealtimeStateRepository, "from_url", lambda *a, **k: repo)
    first = await market_data.intraday_bars("AAPL.US", SimpleNamespace())
    assert [item["trade_session"] for item in first["items"]] == ["pre", "regular", "post", "overnight", "pre"]
    assert first["quote"]["available"] and first["quote"]["trade_session"] == "Pre"
    now += timedelta(minutes=2)
    next_ = await market_data.intraday_bars("AAPL.US", SimpleNamespace(), since=bars[-1].bar_time,
                                           history_version=first["history_version"])
    assert not next_["reset"] and next_["full_snapshot"]
    assert [item["trade_session"] for item in next_["items"]] == ["regular", "post", "overnight", "pre"]


def test_rolling_window_is_elapsed_utc_time_across_daylight_saving():
    now = datetime(2026, 11, 1, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert now.astimezone(timezone.utc) - us_minute_cutoff(now) == timedelta(hours=24)

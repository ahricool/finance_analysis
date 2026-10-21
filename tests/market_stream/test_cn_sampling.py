from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from finance_analysis.integrations.market_data.models import Market, MarketQuote
from finance_analysis.market_stream.sampling import MinuteSampler
from finance_analysis.market_stream.session import cache_ttl, display_day, in_session
from finance_analysis.market_stream.watchlist_monitor import load_watchlist_targets
from finance_analysis.market_stream.quality import indicator_tail

AT = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)


def quote(at=AT, price=10, volume=1000):
    return MarketQuote(
        "600519.SH",
        Market.CN,
        "fuyao",
        "CNY",
        price=price,
        volume=volume,
        amount=volume * 10,
        high=9999,
        low=1,
        quote_time=at,
    )


def test_samples_use_sample_extremes_and_cumulative_deltas_without_double_counting():
    sampler = MinuteSampler()
    sampler.observe(quote(), AT)
    assert sampler.observe(quote(volume=1500), AT) is None
    sampler.observe(quote(AT + timedelta(seconds=10), price=12, volume=1010), AT + timedelta(seconds=10))
    bar = sampler.observe(quote(AT + timedelta(seconds=20), price=9, volume=1020), AT + timedelta(seconds=20))
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (10, 12, 9, 9, 20)
    assert bar.sampled and bar.partial and bar.sample_count == 3
    assert sampler.observe(quote(AT + timedelta(seconds=21)), AT + timedelta(minutes=1)) is None
    completed = sampler.advance(AT + timedelta(minutes=1))
    assert len(completed) == 1 and completed[0].confirmed
    assert not sampler.advance(AT + timedelta(minutes=1))


def test_next_minute_can_be_complete_and_gaps_reset_indicator_history():
    sampler = MinuteSampler()
    for second in range(0, 120, 10):
        at = AT + timedelta(seconds=second)
        sampler.advance(at)
        sampler.observe(quote(at, volume=1000 + second), at)
    bar = sampler.advance(AT + timedelta(minutes=2))[0]
    assert not bar.partial and bar.volume == 60 and bar.sample_count == 6
    bars = [replace(bar, bar_time=AT + timedelta(minutes=i), partial=False) for i in range(5)]
    bars.append(replace(bar, bar_time=AT + timedelta(minutes=7)))
    assert len(indicator_tail(bars, "CN")) == 1
    bars[-1].partial = True
    assert indicator_tail(bars, "CN") == []


def test_stale_future_missing_timestamp_and_lunch_do_not_create_bars():
    sampler = MinuteSampler()
    for value in [
        replace(quote(), quote_time=None),
        quote(AT - timedelta(minutes=1)),
        quote(AT + timedelta(seconds=10)),
    ]:
        assert sampler.observe(value, AT) is None
    lunch = AT.replace(hour=4)
    assert not in_session("CN", lunch)
    assert sampler.observe(quote(lunch), lunch) is None


def test_volume_reset_and_sparse_minute_are_partial():
    sampler = MinuteSampler()
    sampler.observe(quote(volume=1000), AT)
    bar = sampler.observe(quote(AT + timedelta(seconds=10), volume=900), AT + timedelta(seconds=10))
    assert bar.partial and bar.volume == 0
    assert sampler.advance(AT + timedelta(minutes=1))[0].partial


def test_targets_union_watchlists_and_holdings_with_market_normalization():
    repo = SimpleNamespace(list_all=lambda: [SimpleNamespace(code="AAPL", market_type="US")])
    portfolio = SimpleNamespace(monitored_symbols=lambda: [("AAPL.US", "US"), ("600519.SH", "CN"), ("920001.BJ", "CN")])
    result = load_watchlist_targets(repo, portfolio)
    assert set(result) == {"AAPL.US", "600519.SH", "920001.BJ"}


def test_latest_session_survives_weekend_and_holiday_and_us_early_close():
    saturday = datetime(2026, 7, 18, 14, tzinfo=timezone.utc)
    day = display_day("US", saturday)
    assert str(day) == "2026-07-17"
    assert cache_ttl("US", day, saturday) > 2 * 86400
    holiday = datetime(2026, 10, 3, 2, tzinfo=timezone.utc)
    assert not in_session("CN", holiday)
    assert str(display_day("CN", holiday)) == "2026-09-30"
    assert cache_ttl("CN", display_day("CN", holiday), holiday) > 4 * 86400
    assert not in_session("US", datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_cn_feed_batches_targets_without_a_longbridge_connection(monkeypatch):
    from finance_analysis.market_stream.cn_feed import CnQuoteFeed
    from finance_analysis.market_stream.service import MarketStreamService
    from finance_analysis.market_stream.config import MarketStreamConfig
    from finance_analysis.market_stream.symbol_state import SubscriptionTarget
    from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
    from tests.market_stream.fakes import FakeRedis

    calls = []

    def fetch(symbols, *, providers):
        calls.append((symbols, providers))
        return SimpleNamespace(data={symbol: replace(quote(), symbol=symbol) for symbol in symbols})

    app = MarketStreamService(
        config=MarketStreamConfig(redis_url="redis://unused"), repository=RealtimeStateRepository(FakeRedis())
    )
    app.cn_feed = CnQuoteFeed(app, SimpleNamespace(get_realtime_quotes=fetch))
    targets = {symbol: SubscriptionTarget(symbol, "CN") for symbol in ["600519.SH", "000001.SZ"]}
    await app.cn_feed.reconcile(targets)
    monkeypatch.setattr("finance_analysis.market_stream.cn_feed.utc_now", lambda: AT)
    await app.cn_feed.tick()
    assert calls == [(["000001.SZ", "600519.SH"], ("fuyao",))]
    assert set(app.quotes) == set(targets)
    assert all(bar.sampled for bar in app.current_candles.values())
    await app.cn_feed.reconcile({})
    assert not app.quotes and not app.cn_feed.states

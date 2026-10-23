from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from finance_analysis.integrations.market_data.models import BatchBarResult, MinuteBarsRequest
from finance_analysis.integrations.market_data.providers.cn_intraday import CnIntradayProvider
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.cn_feed import CnQuoteFeed
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.market_stream.quality import indicator_tail
from finance_analysis.market_stream.service import MarketStreamService
from finance_analysis.market_stream.symbol_state import SubscriptionTarget
from tests.market_stream.fakes import FakeRedis
from tests.test_cn_intraday_provider import sina_row

NOW = datetime(2026, 10, 23, 1, 33, 10, tzinfo=timezone.utc)
SYMBOL = "600000.SH"


def result():
    provider = CnIntradayProvider(
        "sina_intraday", lambda symbol: [sina_row(at) for at in ["09:31", "09:32", "09:33", "09:34"]]
    )
    return provider.fetch_minute_bars(
        MinuteBarsRequest((SYMBOL,), NOW.replace(minute=30, second=0), NOW, include_incomplete=True)
    )


def app_with(fetch):
    app = MarketStreamService(
        config=MarketStreamConfig(redis_url="redis://unused"), repository=RealtimeStateRepository(FakeRedis())
    )
    app.cn_feed = CnQuoteFeed(app, SimpleNamespace(get_minute_bars=fetch))
    return app


@pytest.mark.asyncio
async def test_native_warmup_replace_and_legacy_migration_never_emit_sampled_candles(monkeypatch):
    value = result()
    app = app_with(lambda *args, **kwargs: value)
    monkeypatch.setattr("finance_analysis.market_stream.cn_feed.utc_now", lambda: NOW)
    await app.cn_feed.reconcile({SYMBOL: SubscriptionTarget(SYMBOL, "CN")})
    await app.cn_feed.tick_minutes()
    bars = list(app.bars_1m[SYMBOL])
    assert len(bars) == 4 and all(not bar.sampled for bar in bars)
    assert [bar.confirmed for bar in bars] == [True, True, True, False]
    assert len(await app.repository.get_recent_bars(SYMBOL, 420)) == 3
    assert not (await app.repository.get_current_candle(SYMBOL)).confirmed
    # A competing source publishes its complete window, removing obsolete source rows.
    value = replace(value, data={SYMBOL: [replace(bar, provider="tencent_intraday") for bar in value.data[SYMBOL][1:]]})
    await app.cn_feed.tick_minutes()
    cached = await app.repository.get_recent_bars(SYMBOL, 420)
    assert len(cached) == 2 and all(bar.source == "tencent_intraday" for bar in cached)
    app2 = app_with(lambda *args, **kwargs: BatchBarResult())
    await app2.repository.upsert_bars(SYMBOL, [replace(bars[0], sampled=True, source="fuyao_sampled")])
    await app2.cn_feed.reconcile({SYMBOL: SubscriptionTarget(SYMBOL, "CN")})
    assert not await app2.repository.get_recent_bars(SYMBOL, 420)


@pytest.mark.asyncio
async def test_failed_feeds_keep_last_valid_window_and_removed_symbols_ignore_late_results(monkeypatch):
    app = app_with(lambda *args, **kwargs: result())
    monkeypatch.setattr("finance_analysis.market_stream.cn_feed.utc_now", lambda: NOW)
    await app.cn_feed.reconcile({SYMBOL: SubscriptionTarget(SYMBOL, "CN")})
    await app.cn_feed.tick_minutes()
    previous = list(app.bars_1m[SYMBOL])
    app.cn_feed.market_data.get_minute_bars = lambda *args, **kwargs: BatchBarResult(
        failed_symbols={SYMBOL: "both unavailable"}
    )
    await app.cn_feed.tick_minutes()
    assert list(app.bars_1m[SYMBOL]) == previous and not app.cn_feed.minute_healthy
    owners = app.cn_feed.states

    def late(*args, **kwargs):
        owners.pop(SYMBOL)
        return result()

    app.cn_feed.market_data.get_minute_bars = late
    await app.cn_feed.tick_minutes()
    assert list(app.bars_1m[SYMBOL]) == previous


def test_native_missing_minutes_break_indicators_but_lunch_does_not():
    from finance_analysis.market_stream.sampling import MinuteSampler
    from tests.market_stream.test_cn_sampling import AT, quote

    sampler = MinuteSampler()
    bar = sampler.observe(quote(), AT)
    native = replace(bar, sampled=False, partial=False)
    assert len(indicator_tail([native, replace(native, bar_time=AT + timedelta(minutes=2))], "CN")) == 1
    am = replace(native, bar_time=AT.replace(hour=3, minute=29))
    pm = replace(native, bar_time=AT.replace(hour=5, minute=0))
    assert len(indicator_tail([am, pm], "CN")) == 2


@pytest.mark.asyncio
async def test_close_retries_failed_atomic_write_then_stops_after_final_closed_minute(monkeypatch):
    clock = NOW.replace(hour=7, minute=0, second=30)
    provider = CnIntradayProvider("sina_intraday", lambda symbol: [sina_row("15:00")])
    final = provider.fetch_minute_bars(MinuteBarsRequest((SYMBOL,), NOW.replace(minute=30, second=0), clock))
    calls = []

    def fetch(*args, **kwargs):
        calls.append(kwargs)
        return final

    app = app_with(fetch)
    monkeypatch.setattr("finance_analysis.market_stream.cn_feed.utc_now", lambda: clock)
    await app.cn_feed.reconcile({SYMBOL: SubscriptionTarget(SYMBOL, "CN")})
    app.repository.redis.fail_execute = True
    await app.cn_feed.tick_minutes()
    assert SYMBOL not in app.cn_feed._settled
    assert not app.cn_feed.minute_healthy
    await app.cn_feed.tick_minutes()
    await app.cn_feed.tick_minutes()
    assert len(calls) == 2
    cached, current = await app.repository.get_intraday_snapshot(SYMBOL)
    assert len(cached) == 1 and current.confirmed
    assert current.bar_time == clock.replace(hour=6, minute=59, second=0)


@pytest.mark.asyncio
async def test_cn_api_returns_revised_full_window_even_with_since_without_resetting_selection(monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints import market_data

    app = app_with(lambda *args, **kwargs: result())
    monkeypatch.setattr("finance_analysis.market_stream.cn_feed.utc_now", lambda: NOW)
    await app.cn_feed.reconcile({SYMBOL: SubscriptionTarget(SYMBOL, "CN")})
    await app.cn_feed.tick_minutes()
    monkeypatch.setattr(market_data, "utc_now", lambda: NOW)
    monkeypatch.setattr(market_data, "get_effective_uid", lambda request: 7)
    monkeypatch.setattr(
        market_data, "_load_tracked_stocks", lambda uid, market: [market_data.TrackedStock(SYMBOL, "CN", SYMBOL)]
    )
    monkeypatch.setattr(market_data.RealtimeStateRepository, "from_url", lambda url: app.repository)
    response = await market_data.intraday_bars(SYMBOL, SimpleNamespace(), since=NOW - timedelta(seconds=10))
    assert response["full_snapshot"] and not response["reset"]
    assert len(response["items"]) == 4
    assert {bar["source"] for bar in response["items"]} == {"sina_intraday"}

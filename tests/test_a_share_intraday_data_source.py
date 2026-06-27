# -*- coding: utf-8 -*-
"""Tests for A-share intraday data-source routing."""

from __future__ import annotations

from finance_analysis.integrations.market_data.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from finance_analysis.tasks.jobs.a_share_intraday_analysis.data_source import AShareIntradayDataSource


class _FakeLongbridge:
    def __init__(self, *, quote=None, bars=None):
        self.quote = quote
        self.bars = bars or []
        self.quote_calls = []
        self.bar_calls = []

    def get_realtime_quote(self, code):
        self.quote_calls.append(code)
        return self.quote

    def get_minute_candlesticks(self, code, interval=1, count=240):
        self.bar_calls.append((code, interval, count))
        return list(self.bars)


class _FakeEfinance:
    def __init__(self, bars=None):
        self.bars = bars or []
        self.bar_calls = []

    def get_all_realtime_quotes(self):
        return []

    def get_minute_candlesticks(self, code, interval=1, count=240):
        self.bar_calls.append((code, interval, count))
        return list(self.bars)


class _FakeManager:
    def __init__(self, quote=None):
        self.quote = quote
        self.quote_calls = []

    def get_main_indices(self, region="cn"):
        return []

    def get_market_stats(self):
        return {}

    def get_sector_rankings(self, n):
        return [], []

    def get_realtime_quote(self, code, log_final_failure=True):
        self.quote_calls.append((code, log_final_failure))
        return self.quote


class _NoRealtime:
    fallback_reason = "redis_missing"

    def get_quote(self, *_args, **_kwargs):
        return None

    def get_recent_bars(self, *_args, **_kwargs):
        return None


class _Realtime:
    fallback_reason = None

    def __init__(self, *, quote=None, bars=None):
        self.quote = quote
        self.bars = bars

    def get_quote(self, *_args, **_kwargs):
        return self.quote

    def get_recent_bars(self, *_args, **_kwargs):
        return self.bars


class _BrokenRealtime:
    fallback_reason = "redis_error"

    def get_quote(self, *_args, **_kwargs):
        raise RuntimeError("redis unavailable")

    def get_recent_bars(self, *_args, **_kwargs):
        raise RuntimeError("redis unavailable")


def _bar(close=10.0):
    return {
        "timestamp": "2026-06-25T10:00:00+08:00",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
        "turnover": 1000.0,
    }


def test_quote_prefers_longbridge_for_a_share_symbol():
    lb_quote = UnifiedRealtimeQuote(code="600519", source=RealtimeSource.LONGBRIDGE, price=1200.0)
    manager_quote = UnifiedRealtimeQuote(code="600519", source=RealtimeSource.TENCENT, price=1199.0)
    longbridge = _FakeLongbridge(quote=lb_quote)
    manager = _FakeManager(quote=manager_quote)

    ds = AShareIntradayDataSource(
        data_manager=manager,
        efinance_fetcher=_FakeEfinance(),
        longbridge_fetcher=longbridge,
        realtime_source=_NoRealtime(),
    )

    assert ds.get_quote("600519") is lb_quote
    assert longbridge.quote_calls == ["600519"]
    assert manager.quote_calls == []


def test_quote_prefers_market_streamer_without_calling_longbridge():
    realtime_quote = UnifiedRealtimeQuote(
        code="600519",
        source=RealtimeSource.MARKET_STREAMER,
        price=1201.0,
    )
    longbridge = _FakeLongbridge()
    ds = AShareIntradayDataSource(
        data_manager=_FakeManager(),
        efinance_fetcher=_FakeEfinance(),
        longbridge_fetcher=longbridge,
        realtime_source=_Realtime(quote=realtime_quote),
    )

    assert ds.get_quote("600519") is realtime_quote
    assert longbridge.quote_calls == []


def test_minute_bars_prefer_market_streamer_without_calling_longbridge():
    realtime_bars = [_bar(13.0)]
    longbridge = _FakeLongbridge()
    ds = AShareIntradayDataSource(
        data_manager=_FakeManager(),
        efinance_fetcher=_FakeEfinance(),
        longbridge_fetcher=longbridge,
        realtime_source=_Realtime(bars=realtime_bars),
    )

    assert ds.fetch_minute_bars("600519") == realtime_bars
    assert longbridge.bar_calls == []


def test_quote_falls_back_to_manager_when_longbridge_has_no_data():
    manager_quote = UnifiedRealtimeQuote(code="600519", source=RealtimeSource.TENCENT, price=1199.0)
    longbridge = _FakeLongbridge(quote=None)
    manager = _FakeManager(quote=manager_quote)

    ds = AShareIntradayDataSource(
        data_manager=manager,
        efinance_fetcher=_FakeEfinance(),
        longbridge_fetcher=longbridge,
        realtime_source=_NoRealtime(),
    )

    assert ds.get_quote("600519") is manager_quote
    assert longbridge.quote_calls == ["600519"]
    assert manager.quote_calls == [("600519", False)]


def test_redis_failure_falls_back_without_failing_analysis_data_source():
    lb_quote = UnifiedRealtimeQuote(code="600519", source=RealtimeSource.LONGBRIDGE, price=1200.0)
    longbridge = _FakeLongbridge(quote=lb_quote, bars=[_bar(12.0)])
    ds = AShareIntradayDataSource(
        data_manager=_FakeManager(),
        efinance_fetcher=_FakeEfinance(),
        longbridge_fetcher=longbridge,
        realtime_source=_BrokenRealtime(),
    )

    assert ds.get_quote("600519") is lb_quote
    assert ds.fetch_minute_bars("600519", count=20)[0]["close"] == 12.0


def test_minute_bars_prefer_longbridge_for_a_share_symbol():
    longbridge = _FakeLongbridge(bars=[_bar(12.0)])
    efinance = _FakeEfinance(bars=[_bar(11.0)])

    ds = AShareIntradayDataSource(
        data_manager=_FakeManager(),
        efinance_fetcher=efinance,
        longbridge_fetcher=longbridge,
        realtime_source=_NoRealtime(),
    )

    bars = ds.fetch_minute_bars("600519", interval=1, count=20)

    assert len(bars) == 1
    assert bars[0]["close"] == 12.0
    assert longbridge.bar_calls == [("600519", 1, 20)]
    assert efinance.bar_calls == []


def test_minute_bars_fall_back_to_efinance_for_benchmark_index_code():
    longbridge = _FakeLongbridge(bars=[_bar(12.0)])
    efinance = _FakeEfinance(bars=[_bar(11.0)])

    ds = AShareIntradayDataSource(
        data_manager=_FakeManager(),
        efinance_fetcher=efinance,
        longbridge_fetcher=longbridge,
        realtime_source=_NoRealtime(),
    )

    bars = ds.fetch_minute_bars("000300", interval=1, count=20)

    assert len(bars) == 1
    assert bars[0]["close"] == 11.0
    assert longbridge.bar_calls == []
    assert efinance.bar_calls == [("000300", 1, 20)]

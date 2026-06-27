from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.integrations.market_data.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from finance_analysis.tasks.jobs.us_intraday_analysis import (
    USIntradayAnalysisService,
    aggregate_bars,
    compute_intraday_metrics,
    cumulative_vwap_series,
    evaluate_signal_candidates,
    filter_current_trading_day_bars,
    is_us_market_open,
    parse_llm_json_response,
)
from finance_analysis.tasks.jobs.us_intraday_analysis.data_source import IntradayDataSource
from finance_analysis.tasks.jobs.us_intraday_analysis.lock import (
    release_us_intraday_running_lock,
    try_acquire_us_intraday_lock,
)
from finance_analysis.tasks.jobs.us_intraday_analysis.metrics import _change_over_minutes, _volume_ratio_5m
from finance_analysis.tasks.lifecycle import TaskSkipped


US_EASTERN = ZoneInfo("America/New_York")


def _bar(ts: datetime, open_price: float, close: float, volume: int = 100) -> dict:
    high = max(open_price, close) + 0.05
    low = min(open_price, close) - 0.05
    return {
        "timestamp": ts.isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "turnover": close * volume,
    }


def _bars(start: datetime, count: int, price: float = 100.0, step: float = 0.1, volume: int = 100) -> list[dict]:
    rows = []
    current = price
    for index in range(count):
        close = current + step
        rows.append(_bar(start + timedelta(minutes=index), current, close, volume=volume))
        current = close
    return rows


def test_filter_current_trading_day_bars_keeps_only_current_regular_session():
    now = datetime(2026, 6, 10, 10, 15, 20, tzinfo=US_EASTERN)
    previous = _bar(datetime(2026, 6, 9, 15, 59, tzinfo=US_EASTERN), 90, 91)
    premarket = _bar(datetime(2026, 6, 10, 9, 10, tzinfo=US_EASTERN), 99, 100)
    current = _bar(datetime(2026, 6, 10, 10, 14, tzinfo=US_EASTERN), 100, 101)
    incomplete = _bar(datetime(2026, 6, 10, 10, 15, tzinfo=US_EASTERN), 101, 102)

    result = filter_current_trading_day_bars([incomplete, previous, current, premarket], now=now)

    assert [item["timestamp"] for item in result] == [current["timestamp"]]


def test_filter_current_trading_day_bars_converts_timezone_without_local_timezone():
    now = datetime(2026, 6, 10, 10, 15, 20, tzinfo=US_EASTERN)
    utc_bar = _bar(datetime(2026, 6, 10, 14, 14, tzinfo=timezone.utc), 100, 101)

    result = filter_current_trading_day_bars([utc_bar], now=now)

    assert len(result) == 1
    assert result[0]["timestamp"].endswith("10:14:00-04:00")


def test_yfinance_fallback_bars_are_filtered(monkeypatch):
    now = datetime(2026, 6, 10, 10, 15, 20, tzinfo=US_EASTERN)

    class _FakeLongbridge:
        def get_minute_candlesticks(self, *_args, **_kwargs):
            return []

    class _FakeYfinanceFetcher:
        pass

    class _NoRealtime:
        fallback_reason = "redis_missing"

        def get_recent_bars(self, *_args, **_kwargs):
            return None

    def fake_yfinance(symbol: str, *, now=None, include_incomplete=False):
        assert symbol == "NVDA"
        return filter_current_trading_day_bars(
            [
                _bar(datetime(2026, 6, 9, 15, 59, tzinfo=US_EASTERN), 90, 91),
                _bar(datetime(2026, 6, 10, 10, 14, tzinfo=US_EASTERN), 100, 101),
                _bar(datetime(2026, 6, 10, 10, 15, tzinfo=US_EASTERN), 101, 102),
            ],
            now=now,
            include_incomplete=include_incomplete,
        )

    monkeypatch.setattr(IntradayDataSource, "_fetch_yfinance_1m_bars", staticmethod(fake_yfinance))
    source = IntradayDataSource(
        _FakeLongbridge(),
        _FakeYfinanceFetcher(),
        realtime_source=_NoRealtime(),
    )

    result = source.fetch_1m_bars("NVDA", now=now)

    assert len(result) == 1
    assert result[0]["timestamp"].endswith("10:14:00-04:00")


def test_us_data_source_prefers_market_streamer_for_quote_and_bars():
    realtime_quote = UnifiedRealtimeQuote(
        code="NVDA",
        source=RealtimeSource.MARKET_STREAMER,
        price=150.0,
    )
    realtime_bars = [_bar(datetime(2026, 6, 10, 10, 14, tzinfo=US_EASTERN), 149, 150)]

    class _Realtime:
        fallback_reason = None

        def get_quote(self, *_args, **_kwargs):
            return realtime_quote

        def get_recent_bars(self, *_args, **_kwargs):
            return realtime_bars

    class _Longbridge:
        def get_realtime_quote(self, *_args, **_kwargs):
            raise AssertionError("Longbridge quote should not be called")

        def get_minute_candlesticks(self, *_args, **_kwargs):
            raise AssertionError("Longbridge bars should not be called")

    source = IntradayDataSource(
        _Longbridge(),
        object(),  # type: ignore[arg-type]
        realtime_source=_Realtime(),
    )

    assert source.fetch_quote("NVDA") is realtime_quote
    assert source.fetch_1m_bars("NVDA") == realtime_bars


def test_aggregate_bars_builds_5m_ohlcv():
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    bars = [_bar(start + timedelta(minutes=i), 100 + i, 100.5 + i, volume=10 + i) for i in range(6)]

    result = aggregate_bars(bars, 5)

    assert len(result) == 2
    assert result[0]["timestamp"].endswith("09:30:00-04:00")
    assert result[0]["open"] == 100
    assert result[0]["close"] == 104.5
    assert result[0]["volume"] == sum(range(10, 15))
    assert result[1]["open"] == 105
    assert result[1]["close"] == 105.5


def test_aggregate_bars_complete_only_excludes_current_5m_bucket():
    start = datetime(2026, 6, 10, 10, 10, tzinfo=US_EASTERN)
    bars = _bars(start, 10)

    at_1015 = aggregate_bars(bars, 5, now=datetime(2026, 6, 10, 10, 15, 20, tzinfo=US_EASTERN), complete_only=True)
    at_1020 = aggregate_bars(bars, 5, now=datetime(2026, 6, 10, 10, 20, 1, tzinfo=US_EASTERN), complete_only=True)

    assert [item["timestamp"] for item in at_1015] == ["2026-06-10T10:10:00-04:00"]
    assert [item["timestamp"] for item in at_1020] == [
        "2026-06-10T10:10:00-04:00",
        "2026-06-10T10:15:00-04:00",
    ]


def test_aggregate_bars_does_not_cross_dates():
    bars = [
        _bar(datetime(2026, 6, 9, 15, 59, tzinfo=US_EASTERN), 90, 91),
        _bar(datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN), 100, 101),
    ]

    result = aggregate_bars(bars, 5)

    assert len(result) == 2
    assert result[0]["timestamp"].startswith("2026-06-09")
    assert result[1]["timestamp"].startswith("2026-06-10")


def test_volume_ratio_uses_only_complete_buckets():
    start = datetime(2026, 6, 10, 10, 0, tzinfo=US_EASTERN)
    bars = []
    for bucket in range(4):
        volume = 100 if bucket < 3 else 300
        bars.extend(_bars(start + timedelta(minutes=bucket * 5), 5, price=100 + bucket, volume=volume))
    bars_5m = aggregate_bars(
        bars,
        5,
        now=datetime(2026, 6, 10, 10, 20, 1, tzinfo=US_EASTERN),
        complete_only=True,
    )

    assert _volume_ratio_5m(bars_5m) == 3.0


def test_cumulative_vwap_series_and_crosses_are_correct():
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    bars = [
        _bar(start, 100, 100, volume=10),
        _bar(start + timedelta(minutes=1), 100, 98, volume=10),
        _bar(start + timedelta(minutes=2), 98, 101, volume=10),
    ]

    series = cumulative_vwap_series(bars)
    metrics = compute_intraday_metrics("NVDA", bars, quote=None)

    assert series == [100.0, 99.0, 99.6667]
    assert metrics["crossed_above_vwap"] is True


def test_cumulative_vwap_down_cross_and_zero_volume_are_safe():
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    bars = [
        _bar(start, 100, 100, volume=0),
        _bar(start + timedelta(minutes=1), 100, 103, volume=10),
        _bar(start + timedelta(minutes=2), 103, 99, volume=10),
    ]
    bars[1]["turnover"] = 1000

    metrics = compute_intraday_metrics("NVDA", bars, quote=None)

    assert cumulative_vwap_series([bars[0]]) == [None]
    assert metrics["crossed_below_vwap"] is True


def test_change_over_minutes_requires_real_coverage():
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    thirteen_bars = _bars(start, 13)
    fifteen_bars = _bars(start, 15)

    assert _change_over_minutes(thirteen_bars, 15) is None
    assert _change_over_minutes(fifteen_bars, 15) is not None
    assert _change_over_minutes(fifteen_bars, 60) is None


def test_evaluate_signal_candidates_detects_normal_breakout():
    metrics = {
        "change_5m": 0.4,
        "change_15m": 0.9,
        "relative_to_qqq_15m": 0.4,
        "volume_ratio_5m": 1.4,
        "price_above_vwap": True,
        "high_distance_pct": 0.7,
    }

    candidates = evaluate_signal_candidates(metrics)

    assert candidates[0]["signal_type"] == "relative_strength_breakout"
    assert candidates[0]["rule_strength"] == "normal"
    assert candidates[0]["score"] == 5.0
    assert candidates[0]["matched_conditions"]


def test_evaluate_signal_candidates_detects_strong_breakout():
    metrics = {
        "change_5m": 0.95,
        "change_15m": 1.8,
        "relative_to_qqq_15m": 0.9,
        "volume_ratio_5m": 2.4,
        "price_above_vwap": True,
        "near_intraday_high": True,
    }

    candidates = evaluate_signal_candidates(metrics)

    assert [item["signal_type"] for item in candidates] == ["relative_strength_breakout"]
    assert candidates[0]["rule_strength"] == "strong"
    assert candidates[0]["severity"] == "high"


def test_breakout_requires_at_least_four_scored_conditions():
    metrics = {
        "change_5m": 0.4,
        "change_15m": 0.9,
        "relative_to_qqq_15m": 0.4,
        "volume_ratio_5m": 1.0,
        "price_above_vwap": True,
        "high_distance_pct": 2.0,
    }

    assert evaluate_signal_candidates(metrics) == []


def test_weak_to_strong_and_strong_to_weak_candidates():
    weak_to_strong = {
        "price_above_vwap": True,
        "early_relative_to_qqq": -0.25,
        "relative_to_qqq_15m": 0.2,
        "change_15m": 0.7,
        "last_two_above_vwap": True,
        "volume_ratio_5m": 1.4,
    }
    strong_to_weak = {
        "price_below_vwap": True,
        "early_relative_to_qqq": 0.4,
        "relative_to_qqq_15m": -0.2,
        "change_5m": -0.5,
        "last_two_below_vwap": True,
        "volume_ratio_5m": 1.4,
    }

    assert evaluate_signal_candidates(weak_to_strong)[0]["signal_type"] == "weak_to_strong_reversal"
    assert evaluate_signal_candidates(strong_to_weak)[0]["signal_type"] == "relative_strength_failure"


def test_none_metrics_do_not_score():
    metrics = {
        "price_above_vwap": True,
        "early_relative_to_qqq": None,
        "relative_to_qqq_15m": 0.2,
        "change_15m": 0.7,
        "last_two_above_vwap": True,
        "volume_ratio_5m": 1.4,
    }

    candidates = evaluate_signal_candidates(metrics)

    assert candidates[0]["score"] == 4.0
    assert "early_relative_to_qqq<=-0.2" in candidates[0]["failed_conditions"]


def test_compute_intraday_metrics_relative_strength_and_vwap():
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    bars = []
    price = 100.0
    for i in range(70):
        next_price = price * (1.0004 if i < 55 else 1.002)
        bars.append(_bar(start + timedelta(minutes=i), price, next_price, volume=100 if i < 65 else 500))
        price = next_price

    metrics = compute_intraday_metrics(
        "NVDA",
        bars,
        quote=None,
        benchmark_metrics={"change_15m": 0.2, "first_hour_change": 0.5},
        sector_metrics={"SOXX": {"change_15m": 0.4}},
    )

    assert metrics["price"] == bars[-1]["close"]
    assert metrics["vwap"] is not None
    assert metrics["change_15m"] > 0.2
    assert metrics["relative_to_qqq_15m"] == round(metrics["change_15m"] - 0.2, 4)
    assert metrics["relative_to_sector_15m"]["SOXX"] == round(metrics["change_15m"] - 0.4, 4)
    assert metrics["volume_ratio_5m"] > 1


def test_relative_to_sectors_ignores_non_metric_entries():
    from finance_analysis.tasks.jobs.us_intraday_analysis.metrics import _relative_to_sectors

    relative = _relative_to_sectors(
        1.5,
        {
            "SOXX": {"change_15m": 0.4},
            "market_news": [{"title": "headline"}],
        },
    )

    assert relative == {"SOXX": 1.1}
    assert "market_news" not in relative


def test_parse_llm_json_response_repairs_fenced_json():
    parsed = parse_llm_json_response(
        """```json
        {
          "final_decision": "watch",
          "need_notification": true,
          "confidence": 0.7,
        }
        ```"""
    )

    assert parsed is not None
    assert parsed["final_decision"] == "watch"
    assert parsed["need_notification"] is True


def test_is_us_market_open_regular_session():
    assert is_us_market_open(datetime(2026, 6, 10, 10, 0, tzinfo=US_EASTERN)) is True
    assert is_us_market_open(datetime(2026, 6, 10, 8, 0, tzinfo=US_EASTERN)) is False


class _FakeLongbridge:
    def __init__(self, bars_by_symbol: dict[str, list[dict]], missing_quotes: set[str] | None = None):
        self.bars_by_symbol = bars_by_symbol
        self.missing_quotes = missing_quotes or set()

    def get_minute_candlesticks(self, symbol, interval=1, count=420):
        assert count == 420
        return self.bars_by_symbol.get(symbol, [])

    def get_realtime_quote(self, symbol):
        if symbol in self.missing_quotes:
            return None
        bars = self.bars_by_symbol.get(symbol) or []
        price = bars[-1]["close"] if bars else 100.0
        return UnifiedRealtimeQuote(code=symbol, price=price, volume=1000)

    def get_stock_name(self, symbol):
        return symbol


class _FakeNewsFetcher:
    def is_available(self):
        return False


class _FakeJudge:
    def __init__(self):
        self.seen = []

    def judge_batch(self, candidates, market_context):
        self.seen.extend(candidates)
        return {
            f"{item['symbol']}|{item['signal_type']}": {
                "id": f"{item['symbol']}|{item['signal_type']}",
                "final_decision": "watch",
                "need_notification": True,
                "confidence": 0.8,
            }
            for item in candidates
        }


class _UnavailableJudge:
    def judge_batch(self, candidates, market_context):
        return {}


class _FakeReporter:
    def record_to_calendar(self, signal):
        return 1

    def send_notification(self, signal):
        return True


class _FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, _script, _numkeys, key, token):
        if self.values.get(key) == token:
            self.values.pop(key, None)
            return 1
        return 0


def _service(now: datetime, bars_by_symbol: dict[str, list[dict]], missing_quotes: set[str] | None = None):
    longbridge = _FakeLongbridge(bars_by_symbol, missing_quotes=missing_quotes)
    service = USIntradayAnalysisService(
        config=object(),
        longbridge_fetcher=longbridge,
        news_fetcher=_FakeNewsFetcher(),
        use_lock=False,
    )
    judge = _FakeJudge()
    service.llm_judge = judge
    service.reporter = _FakeReporter()
    return service, judge


def test_service_processes_0946_with_15_complete_bars():
    now = datetime(2026, 6, 10, 9, 46, tzinfo=US_EASTERN)
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    symbol_bars = _bars(start, 15, step=0.25, volume=100)
    symbol_bars[-5:] = [_bar(start + timedelta(minutes=10 + i), 102 + i * 0.2, 103 + i * 0.3, 500) for i in range(5)]
    qqq_bars = _bars(start, 15, step=0.01, volume=100)
    service, judge = _service(now, {"NVDA": symbol_bars, "QQQ": qqq_bars})

    summary = service.run(["NVDA"], now=now)

    assert summary.processed_symbols == 1
    assert summary.candidate_count >= 1
    assert judge.seen[0]["score"] is not None
    assert judge.seen[0]["matched_conditions"]


def test_service_skips_stale_symbol_and_counts_it():
    now = datetime(2026, 6, 10, 10, 0, tzinfo=US_EASTERN)
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    stale_bars = _bars(start, 20)
    valid_bars = _bars(start, 30, step=0.2, volume=300)
    qqq_bars = _bars(start, 30)
    service, _judge = _service(now, {"NVDA": stale_bars, "MSFT": valid_bars, "QQQ": qqq_bars})

    summary = service.run(["NVDA", "MSFT"], now=now)

    assert summary.stale_symbols == 1
    assert summary.filter_failure_counts["stale_bars"] == 1


def test_service_marks_llm_unavailable_warning_and_summary_json():
    now = datetime(2026, 6, 10, 9, 46, tzinfo=US_EASTERN)
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    service, _judge = _service(now, {"NVDA": _bars(start, 15, step=0.3, volume=500), "QQQ": _bars(start, 15)})
    service.llm_judge = _UnavailableJudge()

    summary = service.run(["NVDA"], now=now)

    assert summary.warnings
    assert summary.degraded is True
    json.dumps(summary.to_dict(), ensure_ascii=False)


def test_us_intraday_lock_blocks_same_window_until_ttl():
    redis = _FakeRedis()
    first = try_acquire_us_intraday_lock(trading_date="2026-06-10", window_time="09:46", client=redis)
    second = try_acquire_us_intraday_lock(trading_date="2026-06-10", window_time="09:46", client=redis)

    try:
        assert first is not None
        assert second is None
    finally:
        release_us_intraday_running_lock(first)


def test_service_lock_competition_raises_task_skipped():
    now = datetime(2026, 6, 10, 9, 46, tzinfo=US_EASTERN)
    redis = _FakeRedis()
    first = try_acquire_us_intraday_lock(trading_date="2026-06-10", window_time="09:46", client=redis)
    service = USIntradayAnalysisService(
        config=object(),
        longbridge_fetcher=_FakeLongbridge({}),
        news_fetcher=_FakeNewsFetcher(),
        lock_client=redis,
    )

    try:
        with pytest.raises(TaskSkipped):
            service.run(["NVDA"], now=now)
    finally:
        release_us_intraday_running_lock(first)

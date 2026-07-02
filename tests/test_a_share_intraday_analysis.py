# -*- coding: utf-8 -*-
"""Service-level tests for the A-share intraday analysis task."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.llm import (
    AShareIntradayLLMJudge,
    build_batch_prompt,
    candidate_id,
    normalize_verdict,
    parse_llm_batch_results,
    parse_llm_json_response,
)
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.lock import (
    release_a_share_intraday_lock,
    try_acquire_a_share_intraday_lock,
)
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.market_calendar import (
    is_a_share_intraday_analysis_time,
)
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.models import AShareSignalResult
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.notifications import (
    AShareIntradayReporter,
    reset_cooldown_store,
)
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.domain_service import (
    AShareIntradayAnalysisService,
    compute_market_breadth,
    determine_market_regime,
)
from finance_analysis.tasks.celery.jobs.intraday_signal_state import IntradaySignalStateStore
from finance_analysis.tasks.lifecycle import TaskSkipped

SH = ZoneInfo("Asia/Shanghai")
SERVICE_MODULE = "finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.domain_service"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
def _row(code, name, price, pre_close, *, open_=None, high=None, low=None, change_pct=None, amount=1.0e8):
    if change_pct is None and pre_close:
        change_pct = round((price - pre_close) / pre_close * 100, 4)
    return {
        "code": code,
        "name": name,
        "price": price,
        "pre_close": pre_close,
        "open": open_ if open_ is not None else pre_close,
        "high": high if high is not None else max(price, open_ or pre_close),
        "low": low if low is not None else min(price, open_ or pre_close),
        "change_pct": change_pct,
        "amount": amount,
        "turnover_rate": 3.0,
        "amplitude": 2.0,
    }


def _declining_bars(start: datetime, code_close_start: float, code_close_end: float, count: int = 20):
    bars = []
    step = (code_close_end - code_close_start) / max(1, count - 1)
    prev = code_close_start + 0.1
    for i in range(count):
        close = round(code_close_start + step * i, 3)
        bars.append(
            {
                "timestamp": (start + timedelta(minutes=i)).isoformat(),
                "open": prev,
                "high": max(prev, close) + 0.02,
                "low": min(prev, close) - 0.02,
                "close": close,
                "volume": 1000 + i * 100,
                "turnover": close * (1000 + i * 100),
            }
        )
        prev = close
    return bars


class FakeDataSource:
    def __init__(self, rows, bars_by_code, indices=None, sectors=None):
        self.rows = rows
        self.bars_by_code = bars_by_code
        self.indices = indices or []
        self.sectors = sectors or ([], [])
        self.minute_calls: List[str] = []

    def get_market_snapshot_rows(self):
        return list(self.rows)

    def get_main_indices(self):
        return list(self.indices)

    def get_market_stats(self):
        return {}

    def get_sector_rankings(self, n=5):
        return self.sectors

    def fetch_minute_bars(self, code, *, interval=1, count=240, now=None):
        self.minute_calls.append(code)
        return list(self.bars_by_code.get(code, []))

    def get_quote(self, code):
        return None


class FailingSnapshotDataSource(FakeDataSource):
    def get_market_snapshot_rows(self):
        return []


class FakeLLM:
    def __init__(self, verdicts=None, available=True):
        self._verdicts = verdicts or {}
        self._available = available
        self.batches: List[List[Dict[str, Any]]] = []

    def is_available(self):
        return self._available

    def judge_batch(self, candidates, market_context):
        self.batches.append(list(candidates))
        if not self._available:
            return {}
        out = {}
        for cand in candidates:
            cid = cand["id"]
            if cid in self._verdicts:
                out[cid] = self._verdicts[cid]
        return out


class FakeNotifier:
    def __init__(self, result=True, raises=False):
        self.result = result
        self.raises = raises
        self.calls: List[Dict[str, Any]] = []

    def send(self, content, **kwargs):
        self.calls.append({"content": content, **kwargs})
        if self.raises:
            raise RuntimeError("notify boom")
        return self.result


def _make_reporter(notifier=None):
    calendar_entries: List[Dict[str, Any]] = []

    def _writer(*, time, title, content, calendar_type):
        calendar_entries.append({"title": title, "type": calendar_type, "content": content})
        return len(calendar_entries)

    reporter = AShareIntradayReporter(
        notification_factory=(lambda: notifier) if notifier is not None else None,
        calendar_writer=_writer,
    )
    reporter.calendar_entries = calendar_entries  # type: ignore[attr-defined]
    return reporter


def _make_service(data_source, llm, reporter, watchlist):
    return AShareIntradayAnalysisService(
        config=None,
        data_source=data_source,
        llm_judge=llm,
        reporter=reporter,
        watchlist_provider=lambda: watchlist,
        use_lock=False,
        signal_state_store=IntradaySignalStateStore(redis_client=False),
    )


@pytest.fixture(autouse=True)
def _clear_cooldown():
    reset_cooldown_store()
    yield
    reset_cooldown_store()


def _run_now():
    return datetime(2026, 6, 24, 10, 30, tzinfo=SH)


# ---------------------------------------------------------------------------
# Market breadth (req 22-25)
# ---------------------------------------------------------------------------
def test_market_breadth_counts_up_down_and_limits():
    from datetime import date

    rows = [
        _row("600000", "浦发银行", 11.0, 10.0),  # limit up (+10%)
        _row("600001", "示例A", 9.0, 10.0),       # limit down (-10%)
        _row("600002", "示例B", 10.5, 10.0),      # up
        _row("600003", "示例C", 9.8, 10.0),       # down
        _row("600004", "示例D", 10.0, 10.0),      # flat
    ]
    breadth = compute_market_breadth(rows, date(2026, 6, 24))
    assert breadth["up_count"] == 2  # 11.0 and 10.5
    assert breadth["down_count"] == 2
    assert breadth["flat_count"] == 1
    assert breadth["limit_up_count"] == 1
    assert breadth["limit_down_count"] == 1


def test_market_breadth_detects_opened_limit_up_and_break_rate():
    from datetime import date

    # Touched the 11.0 limit (high) but closed below -> opened from limit up.
    rows = [_row("600000", "示例", 10.6, 10.0, high=11.0, low=10.2, open_=10.3)]
    breadth = compute_market_breadth(rows, date(2026, 6, 24))
    assert breadth["touched_limit_up_count"] == 1
    assert breadth["opened_from_limit_up_count"] == 1
    assert breadth["break_rate"] == 1.0


def test_break_rate_none_when_no_touch():
    from datetime import date

    rows = [_row("600000", "示例", 10.2, 10.0, high=10.3, low=10.0)]
    breadth = compute_market_breadth(rows, date(2026, 6, 24))
    assert breadth["touched_limit_up_count"] == 0
    assert breadth["break_rate"] is None


def test_etf_excluded_from_limit_statistics():
    from datetime import date

    rows = [_row("510300", "沪深300ETF", 4.4, 4.0, high=4.4)]  # +10% but ETF
    breadth = compute_market_breadth(rows, date(2026, 6, 24))
    assert breadth["counted_symbols"] == 0
    assert breadth["limit_up_count"] == 0


def test_determine_market_regime_panic():
    breadth = {
        "counted_symbols": 100,
        "up_count": 10,
        "down_count": 80,
        "limit_up_count": 2,
        "limit_down_count": 40,
        "break_rate": None,
        "up_ratio": 0.1,
    }
    assert determine_market_regime(breadth, {}, [], []) == "panic"


# ---------------------------------------------------------------------------
# Session gating (req 6-12)
# ---------------------------------------------------------------------------
def _empty_service():
    return _make_service(FakeDataSource([], {}), FakeLLM(), _make_reporter(), [])


def test_skips_on_weekend():
    service = _empty_service()
    saturday = datetime(2026, 6, 27, 10, 30, tzinfo=SH)
    with pytest.raises(TaskSkipped):
        service.run(now=saturday)


def test_skips_on_holiday():
    service = _empty_service()
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=False):
        with pytest.raises(TaskSkipped):
            service.run(now=_run_now())


def test_skips_during_lunch():
    service = _empty_service()
    lunch = datetime(2026, 6, 24, 12, 15, tzinfo=SH)
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        with pytest.raises(TaskSkipped):
            service.run(now=lunch)


def test_a_share_intraday_time_boundaries_include_session_end_but_not_lunch():
    assert is_a_share_intraday_analysis_time(datetime(2026, 6, 24, 11, 30, tzinfo=SH))
    assert not is_a_share_intraday_analysis_time(datetime(2026, 6, 24, 11, 31, tzinfo=SH))
    assert is_a_share_intraday_analysis_time(datetime(2026, 6, 24, 13, 0, tzinfo=SH))
    assert is_a_share_intraday_analysis_time(datetime(2026, 6, 24, 15, 0, tzinfo=SH))
    assert not is_a_share_intraday_analysis_time(datetime(2026, 6, 24, 15, 1, tzinfo=SH))


def test_a_share_running_lock_blocks_overlapping_five_minute_windows(tmp_path):
    with patch(
        "finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.lock._lock_path",
        return_value=tmp_path / "a-share.lock",
    ):
        first = try_acquire_a_share_intraday_lock("a_share_intraday:2026-06-24:10:30")
        second = try_acquire_a_share_intraday_lock("a_share_intraday:2026-06-24:10:35")
        try:
            assert first is not None
            assert second is None
        finally:
            release_a_share_intraday_lock(first)


def test_skips_pre_market():
    service = _empty_service()
    pre = datetime(2026, 6, 24, 9, 35, tzinfo=SH)
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        with pytest.raises(TaskSkipped):
            service.run(now=pre)


def test_skips_post_market():
    service = _empty_service()
    post = datetime(2026, 6, 24, 15, 30, tzinfo=SH)
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        with pytest.raises(TaskSkipped):
            service.run(now=post)


def test_morning_and_afternoon_run_succeeds():
    rows = [_row("600002", "示例", 10.1, 10.0)]
    data = FakeDataSource(rows, {})
    service = _make_service(data, FakeLLM(), _make_reporter(), [])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        morning = service.run(now=datetime(2026, 6, 24, 10, 30, tzinfo=SH))
        afternoon = service.run(now=datetime(2026, 6, 24, 14, 0, tzinfo=SH))
    assert morning.market_phase == "morning"
    assert morning.snapshot_time.tzinfo is not None
    assert str(morning.snapshot_time.tzinfo) == "Asia/Shanghai"
    assert afternoon.market_phase == "afternoon"


# ---------------------------------------------------------------------------
# Snapshot failure -> failed; sector failure -> degraded
# ---------------------------------------------------------------------------
def test_snapshot_total_failure_raises():
    service = _make_service(FailingSnapshotDataSource([], {}), FakeLLM(), _make_reporter(), [])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        with pytest.raises(RuntimeError):
            service.run(now=_run_now())


def test_sector_failure_still_completes():
    rows = [_row("600002", "示例", 10.1, 10.0)]
    data = FakeDataSource(rows, {}, sectors=([], []))
    service = _make_service(data, FakeLLM(), _make_reporter(), [])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        summary = service.run(now=_run_now())
    assert summary.market_open is True
    assert any("板块排行" in w for w in summary.warnings)


# ---------------------------------------------------------------------------
# Candidates + minute bars (req 28-37)
# ---------------------------------------------------------------------------
def _scenario_with_watchlist_signal():
    start = datetime(2026, 6, 24, 10, 10, tzinfo=SH)
    # Watchlist stock dropping toward the 9.0 limit-down.
    bars = _declining_bars(start, 9.8, 9.12, count=20)
    rows = [
        _row("600519", "贵州茅台", 9.12, 10.0, open_=9.8, high=9.85, low=9.1),
        _row("600002", "普通A", 10.02, 10.0),  # not anomalous, change<3
        _row("600003", "普通B", 10.01, 10.0),
    ]
    bars_by_code = {"600519": bars}
    return rows, bars_by_code


def test_watchlist_enters_candidate_and_only_candidates_fetch_minute_bars():
    rows, bars_by_code = _scenario_with_watchlist_signal()
    data = FakeDataSource(rows, bars_by_code)
    verdicts = {
        candidate_id("600519", "near_limit_down_risk"): {
            "final_decision": "risk",
            "need_notification": True,
            "summary": "接近跌停",
            "severity": "warning",
        }
    }
    service = _make_service(data, FakeLLM(verdicts), _make_reporter(FakeNotifier()), ["600519"])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        summary = service.run(now=_run_now())

    # The two non-anomalous stocks must not have minute bars fetched.
    assert "600002" not in data.minute_calls
    assert "600003" not in data.minute_calls
    assert "600519" in data.minute_calls
    assert summary.watchlist_symbols == 1
    assert summary.rule_candidate_count >= 1
    assert any(s.signal_type == "near_limit_down_risk" for s in summary.signal_results)


def test_candidate_dedup_when_watchlist_also_market_anomaly():
    rows, bars_by_code = _scenario_with_watchlist_signal()
    data = FakeDataSource(rows, bars_by_code)
    service = _make_service(data, FakeLLM(), _make_reporter(), ["600519"])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        summary = service.run(now=_run_now())
    # 600519 should appear once as a candidate (deduped).
    assert data.minute_calls.count("600519") == 1
    assert summary.snapshot_candidate_count >= 1


def test_insufficient_minute_bars_skipped():
    rows = [_row("600519", "贵州茅台", 9.2, 10.0, open_=9.8, high=9.85, low=9.1)]
    data = FakeDataSource(rows, {"600519": _declining_bars(datetime(2026, 6, 24, 10, 25, tzinfo=SH), 9.5, 9.2, count=4)})
    service = _make_service(data, FakeLLM(), _make_reporter(), ["600519"])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        summary = service.run(now=_run_now())
    assert summary.rule_candidate_count == 0
    assert any("分钟K线不足" in w for w in summary.warnings)


# ---------------------------------------------------------------------------
# LLM (req 48-55)
# ---------------------------------------------------------------------------
def test_llm_batch_maps_by_id_and_ignores_missing():
    cand = {"id": "600519|near_limit_down_risk"}
    results = parse_llm_batch_results(
        '{"results": [{"id": "600519|near_limit_down_risk", "final_decision": "risk", '
        '"need_notification": true, "confidence": 0.8}]}'
    )
    assert results[0]["id"] == cand["id"]


def test_llm_judge_drops_unknown_ids():
    judge = AShareIntradayLLMJudge(config=None, client=_StubClient(
        '{"results": [{"id": "GHOST|x", "final_decision": "risk", "need_notification": true}]}'
    ))
    verdicts = judge.judge_batch([{"id": "600519|near_limit_down_risk"}], {})
    # Positional fallback maps the single ghost result to the real candidate id.
    assert "600519|near_limit_down_risk" in verdicts


def test_parse_llm_json_repairs_fenced_and_trailing_comma():
    parsed = parse_llm_json_response(
        """```json
        {"final_decision": "watch", "need_notification": true, "confidence": 0.7,}
        ```"""
    )
    assert parsed is not None
    assert parsed["final_decision"] == "watch"


def test_normalize_verdict_clamps_enums_and_confidence():
    v = normalize_verdict(
        {
            "id": "x|y",
            "final_decision": "BUY",
            "direction": "up",
            "confidence": 5,
            "driver_type": "aliens",
            "need_notification": "yes",
        }
    )
    assert v["final_decision"] == "ignore"
    assert v["direction"] == "neutral"
    assert v["driver_type"] == "unknown"
    assert v["confidence"] == 1.0
    # decision ignore forces need_notification False
    assert v["need_notification"] is False


def test_prompt_mentions_t1_and_forbids_absolute_orders():
    prompt = build_batch_prompt([{"id": "x|y", "code": "600519"}], {"market_phase": "morning"})
    assert "T+1" in prompt
    assert "追涨" in prompt
    from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.llm import _SYSTEM_PROMPT

    assert "必涨" in _SYSTEM_PROMPT
    assert "JSON" in _SYSTEM_PROMPT


def test_llm_unavailable_risk_signal_falls_back_to_notification():
    rows, bars_by_code = _scenario_with_watchlist_signal()
    data = FakeDataSource(rows, bars_by_code)
    notifier = FakeNotifier()
    service = _make_service(data, FakeLLM(available=False), _make_reporter(notifier), ["600519"])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        summary = service.run(now=_run_now())
    risk_signals = [s for s in summary.signal_results if s.signal_type == "near_limit_down_risk"]
    assert risk_signals and risk_signals[0].fallback_used is True
    assert risk_signals[0].need_notification is True
    assert notifier.calls  # fallback risk alert was sent
    assert "确定性" in notifier.calls[0]["content"]


def test_llm_unavailable_opportunity_signal_not_strongly_alerted():
    service = _make_service(FakeDataSource([], {}), FakeLLM(available=False), _make_reporter(), [])
    fallback = service._signal_from_fallback(
        {
            "id": "600519|abnormal_volume_breakout",
            "code": "600519",
            "name": "贵州茅台",
            "board": "main_board",
            "signal_type": "abnormal_volume_breakout",
            "metrics": {},
        }
    )
    assert fallback.need_notification is False
    assert fallback.fallback_used is True


# ---------------------------------------------------------------------------
# Notification dedup / cooldown (req 56-63)
# ---------------------------------------------------------------------------
def _signal(code="600519", signal_type="near_limit_down_risk", severity="warning"):
    return AShareSignalResult(
        code=code,
        name="贵州茅台",
        signal_type=signal_type,
        board="main_board",
        need_notification=True,
        final_decision="risk",
        metrics={},
        llm_result={"summary": "x"},
        severity=severity,
    )


def test_cooldown_blocks_repeated_same_signal():
    reporter = AShareIntradayReporter()
    sig = _signal()
    first = reporter.filter_signals_for_notification([sig], trading_date="2026-06-24", phase="morning")
    assert len(first) == 1
    reporter.mark_notified(first)
    second = reporter.filter_signals_for_notification([sig], trading_date="2026-06-24", phase="morning")
    assert len(second) == 0


def test_sealed_to_break_open_is_new_signal_and_passes_cooldown():
    reporter = AShareIntradayReporter()
    sealed = _signal(signal_type="limit_up_sealed", severity="info")
    reporter.mark_notified([sealed])
    break_open = _signal(signal_type="limit_up_break_open", severity="warning")
    passed = reporter.filter_signals_for_notification(
        [break_open], trading_date="2026-06-24", phase="morning"
    )
    assert len(passed) == 1


def test_risk_escalation_error_bypasses_cooldown():
    reporter = AShareIntradayReporter()
    sig = _signal(severity="warning")
    reporter.mark_notified([sig])
    escalated = _signal(severity="error")
    passed = reporter.filter_signals_for_notification([escalated], trading_date="2026-06-24", phase="morning")
    assert len(passed) == 1


def test_signal_state_generation_change_bypasses_process_cooldown():
    reporter = AShareIntradayReporter()
    first = _signal(severity="warning")
    first.metrics["state_generation"] = 1
    reporter.mark_notified([first])

    changed = _signal(severity="warning")
    changed.metrics["state_generation"] = 2
    passed = reporter.filter_signals_for_notification(
        [changed],
        trading_date="2026-06-24",
        phase="morning",
    )

    assert len(passed) == 1


def test_five_minute_repeat_does_not_repeat_llm_or_notification_for_unchanged_signal():
    rows, bars_by_code = _scenario_with_watchlist_signal()
    data = FakeDataSource(rows, bars_by_code)
    notifier = FakeNotifier()
    llm = FakeLLM(
        {
            candidate_id("600519", "near_limit_down_risk"): {
                "final_decision": "risk",
                "need_notification": True,
                "summary": "接近跌停",
            }
        }
    )
    service = _make_service(data, llm, _make_reporter(notifier), ["600519"])

    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        first = service.run(now=_run_now())
        repeated = service.run(now=_run_now() + timedelta(minutes=5))

    assert first.llm_candidate_count >= 1
    assert repeated.rule_candidate_count >= 1
    assert repeated.llm_candidate_count == 0
    assert len(llm.batches) == 1
    assert len(notifier.calls) == 1


def test_aggregated_notification_failure_does_not_raise():
    rows, bars_by_code = _scenario_with_watchlist_signal()
    data = FakeDataSource(rows, bars_by_code)
    verdicts = {
        candidate_id("600519", "near_limit_down_risk"): {
            "final_decision": "risk",
            "need_notification": True,
            "summary": "接近跌停",
        }
    }
    reporter = _make_reporter(FakeNotifier(raises=True))
    service = _make_service(data, FakeLLM(verdicts), reporter, ["600519"])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        summary = service.run(now=_run_now())  # must not raise
    assert summary.market_open is True


def test_summary_and_signal_calendar_written_and_json_serializable():
    import json

    rows, bars_by_code = _scenario_with_watchlist_signal()
    data = FakeDataSource(rows, bars_by_code)
    verdicts = {
        candidate_id("600519", "near_limit_down_risk"): {
            "final_decision": "risk",
            "need_notification": True,
            "summary": "接近跌停",
        }
    }
    reporter = _make_reporter(FakeNotifier())
    service = _make_service(data, FakeLLM(verdicts), reporter, ["600519"])
    with patch(f"{SERVICE_MODULE}.is_a_share_trading_day", return_value=True):
        summary = service.run(now=_run_now())

    types = {e["type"] for e in reporter.calendar_entries}  # type: ignore[attr-defined]
    assert "scheduled_a_share_intraday" in types
    assert "a_share_intraday_signal" in types
    # TaskRecord.result must be JSON serializable.
    json.dumps(summary.to_dict())


class _StubClient:
    def __init__(self, text):
        self._text = text

    def is_available(self):
        return True

    def complete_json(self, request):
        class _R:
            text = self._text

        r = _R()
        r.text = self._text
        return r

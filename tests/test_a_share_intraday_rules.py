# -*- coding: utf-8 -*-
"""Tests for A-share intraday bars, metrics and the deterministic rule engine."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.bars import (
    aggregate_bars,
    normalize_bars,
)
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.metrics import (
    compute_a_share_intraday_metrics,
)
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.price_limits import (
    resolve_price_limit_rule,
)
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.rules import (
    evaluate_signal_candidates,
)

SH = ZoneInfo("Asia/Shanghai")


def _bar(ts: datetime, open_price: float, close: float, volume: int = 1000) -> dict:
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


def _signal_types(metrics: dict, phase: str = "morning") -> list[str]:
    return [item["signal_type"] for item in evaluate_signal_candidates(metrics, phase)]


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------
def test_normalize_bars_filters_lunch_and_future_and_dedupes():
    base = datetime(2026, 6, 24, 10, 0, tzinfo=SH)
    now = datetime(2026, 6, 24, 11, 0, tzinfo=SH)
    raw = [
        _bar(base, 10.0, 10.1),
        _bar(base, 10.0, 10.1),  # duplicate timestamp
        _bar(datetime(2026, 6, 24, 12, 15, tzinfo=SH), 10.0, 10.2),  # lunch
        _bar(datetime(2026, 6, 24, 14, 0, tzinfo=SH), 10.0, 10.3),  # future vs now
        _bar(datetime(2026, 6, 24, 10, 30, tzinfo=SH), 10.1, 10.2),
    ]
    bars = normalize_bars(raw, now=now)
    times = [b["timestamp"] for b in bars]
    assert len(bars) == 2  # dup collapsed, lunch + future dropped
    assert times == sorted(times)


def test_normalize_bars_excludes_still_forming_current_minute():
    now = datetime(2026, 6, 24, 11, 30, tzinfo=SH)
    bars = normalize_bars(
        [
            _bar(datetime(2026, 6, 24, 11, 29, tzinfo=SH), 10.0, 10.1),
            _bar(datetime(2026, 6, 24, 11, 30, tzinfo=SH), 10.1, 10.2),
        ],
        now=now,
    )

    assert [bar["timestamp"] for bar in bars] == ["2026-06-24T11:29:00+08:00"]


def test_aggregate_bars_builds_5m_ohlcv():
    start = datetime(2026, 6, 24, 10, 0, tzinfo=SH)
    bars = [_bar(start + timedelta(minutes=i), 10 + i * 0.1, 10.05 + i * 0.1, volume=100 + i) for i in range(6)]
    result = aggregate_bars(bars, 5)
    assert len(result) == 2
    assert result[0]["open"] == 10.0
    assert result[0]["volume"] == sum(range(100, 105))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def test_compute_metrics_vwap_changes_and_relative_strength():
    start = datetime(2026, 6, 24, 10, 0, tzinfo=SH)
    bars = []
    price = 10.0
    for i in range(40):
        nxt = price * (1.001 if i < 30 else 1.004)
        bars.append(_bar(start + timedelta(minutes=i), price, nxt, volume=1000 if i < 35 else 4000))
        price = nxt
    rule = resolve_price_limit_rule(code="600519", name="贵州茅台", pre_close=10.0)
    metrics = compute_a_share_intraday_metrics(
        code="600519",
        name="贵州茅台",
        board="main_board",
        bars_1m=bars,
        quote=None,
        snapshot={"pre_close": 10.0, "open": 10.0, "turnover_rate": 5.0},
        price_limit=rule,
        main_index_metrics={"change_15m": 0.2},
        board_index_metrics={"change_15m": 0.1},
        sector_change_15m=0.3,
    )
    assert metrics["vwap"] is not None
    assert metrics["change_5m"] is not None
    assert metrics["change_15m"] is not None
    assert metrics["relative_to_main_index_15m"] == round(metrics["change_15m"] - 0.2, 4)
    assert metrics["relative_to_sector_15m"] == round(metrics["change_15m"] - 0.3, 4)
    assert metrics["limit_up_price"] == 11.0
    assert metrics["bars_count"] == 40


def test_metrics_touched_limit_up_then_opened():
    start = datetime(2026, 6, 24, 10, 0, tzinfo=SH)
    rule = resolve_price_limit_rule(code="600519", name="某主板", pre_close=10.0)
    bars = []
    # Ramps to the 11.0 limit then pulls back.
    seq = [10.5, 10.8, 11.0, 11.0, 10.7, 10.6]
    prev = 10.2
    for i, close in enumerate(seq):
        bars.append(_bar(start + timedelta(minutes=i), prev, close, volume=2000))
        prev = close
    quote = None
    metrics = compute_a_share_intraday_metrics(
        code="600519",
        name="某主板",
        board="main_board",
        bars_1m=bars,
        quote=quote,
        snapshot={"pre_close": 10.0, "open": 10.2, "price": 10.6},
        price_limit=rule,
    )
    assert metrics["touched_limit_up"] is True
    assert metrics["is_limit_up"] is False
    assert metrics["opened_from_limit_up"] is True


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def _base_metrics(**overrides) -> dict:
    metrics = {
        "has_price_limit": True,
        "limit_up_price": 11.0,
        "limit_down_price": 9.0,
        "distance_to_limit_up_pct": 5.0,
        "distance_to_limit_down_pct": 5.0,
        "is_limit_up": False,
        "is_limit_down": False,
        "touched_limit_up": False,
        "opened_from_limit_up": False,
        "one_word_limit_up": False,
        "change_5m": 0.0,
        "change_15m": 0.0,
        "change_30m": 0.0,
        "opening_gap_pct": 0.0,
        "intraday_volume_ratio": 1.0,
        "price_above_vwap": False,
        "price_below_vwap": False,
        "crossed_above_vwap": False,
        "drawdown_from_high_pct": 0.0,
        "rebound_from_low_pct": 0.0,
        "relative_to_main_index_15m": 0.0,
        "relative_to_sector_15m": 0.0,
    }
    metrics.update(overrides)
    return metrics


def test_rule_near_limit_up_acceleration():
    metrics = _base_metrics(
        distance_to_limit_up_pct=1.5,
        change_5m=1.0,
        change_15m=2.0,
        intraday_volume_ratio=2.0,
        price_above_vwap=True,
    )
    assert "near_limit_up_acceleration" in _signal_types(metrics)


def test_rule_limit_up_sealed():
    metrics = _base_metrics(is_limit_up=True, distance_to_limit_up_pct=0.0)
    assert "limit_up_sealed" in _signal_types(metrics)


def test_rule_limit_up_break_open_is_high_priority():
    metrics = _base_metrics(
        touched_limit_up=True,
        opened_from_limit_up=True,
        drawdown_from_high_pct=2.5,
    )
    assert "limit_up_break_open" in _signal_types(metrics)


def test_rule_strong_to_weak_failure():
    metrics = _base_metrics(
        relative_to_main_index_15m=1.0,
        price_below_vwap=True,
        change_5m=-1.2,
        drawdown_from_high_pct=2.5,
    )
    assert "strong_to_weak_failure" in _signal_types(metrics)


def test_rule_weak_to_strong_reversal():
    metrics = _base_metrics(
        crossed_above_vwap=True,
        change_15m=1.5,
        rebound_from_low_pct=2.0,
        intraday_volume_ratio=1.8,
        relative_to_sector_15m=0.5,
    )
    assert "weak_to_strong_reversal" in _signal_types(metrics)


def test_rule_high_open_low_move():
    metrics = _base_metrics(
        opening_gap_pct=2.0,
        price_below_vwap=True,
        drawdown_from_high_pct=2.5,
        change_15m=-0.5,
    )
    assert "high_open_low_move" in _signal_types(metrics)


def test_rule_abnormal_volume_breakout():
    metrics = _base_metrics(
        intraday_volume_ratio=2.5,
        change_5m=1.0,
        change_15m=2.0,
        price_above_vwap=True,
        relative_to_main_index_15m=1.0,
    )
    assert "abnormal_volume_breakout" in _signal_types(metrics, "morning")


def test_rule_near_limit_down_risk():
    metrics = _base_metrics(
        distance_to_limit_down_pct=1.5,
        change_5m=-1.5,
        price_below_vwap=True,
    )
    assert "near_limit_down_risk" in _signal_types(metrics)


def test_one_word_limit_not_treated_as_chase_opportunity():
    metrics = _base_metrics(
        one_word_limit_up=True,
        is_limit_up=True,
        distance_to_limit_up_pct=0.0,
        change_5m=2.0,
        change_15m=3.0,
        intraday_volume_ratio=3.0,
        price_above_vwap=True,
    )
    types = _signal_types(metrics)
    assert "near_limit_up_acceleration" not in types
    assert "limit_up_sealed" in types


def test_closing_thresholds_differ_from_opening():
    # A breakout-style opportunity fires in the morning but not at the open,
    # where opportunity rules are suppressed and thresholds are stricter.
    metrics = _base_metrics(
        intraday_volume_ratio=2.0,
        change_5m=0.9,
        change_15m=1.6,
        price_above_vwap=True,
        relative_to_main_index_15m=0.9,
    )
    assert "abnormal_volume_breakout" in _signal_types(metrics, "morning")
    assert "abnormal_volume_breakout" not in _signal_types(metrics, "opening")

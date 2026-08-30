from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta

import pytest

from finance_analysis.etf_rotation.classifier import classify_state  # pragma: allowlist secret
from finance_analysis.etf_rotation.config import (  # pragma: allowlist secret
    DEFAULT_CONFIG,
    RETURN_WINDOWS,
    ETFRotationConfig,
)
from finance_analysis.etf_rotation.correlation import rolling_correlations  # pragma: allowlist secret
from finance_analysis.etf_rotation.eligibility import is_absolute_trend_eligible  # pragma: allowlist secret
from finance_analysis.etf_rotation.features import MINIMUM_HISTORY_BARS, calculate_features  # pragma: allowlist secret
from finance_analysis.etf_rotation.models import DailyBar  # pragma: allowlist secret
from finance_analysis.etf_rotation.ranking import calculate_rank_changes, rank_feature  # pragma: allowlist secret
from finance_analysis.etf_rotation.regime import calculate_market_regime  # pragma: allowlist secret
from finance_analysis.etf_rotation.scoring import (  # pragma: allowlist secret
    calculate_factor_scores,
    map_relative_strength_score,
)
from finance_analysis.etf_rotation.selector import (  # pragma: allowlist secret
    public_rotation_action,
    select_candidates,
)


def bars(closes: list[float]) -> list[DailyBar]:
    return [
        DailyBar(date(2026, 1, 1) + timedelta(days=index), close, 1000, 100_000_000)
        for index, close in enumerate(closes)
    ]


def test_fast_features_use_only_twenty_session_history() -> None:
    closes = [100 + index for index in range(21)]
    features = calculate_features(bars(closes))
    assert MINIMUM_HISTORY_BARS == 21
    assert RETURN_WINDOWS == (1, 3, 5, 10, 20)
    assert calculate_features(bars(closes[:-1])) is None
    assert features is not None
    assert features.ret_3d == pytest.approx(120 / 117 - 1)
    assert features.previous_3d_return == pytest.approx(117 / 114 - 1)
    assert features.momentum_acceleration_3d == pytest.approx((120 / 117) - (117 / 114))
    assert features.momentum_acceleration_5d == pytest.approx((120 / 115) - (115 / 110))
    assert features.weighted_slope_5d > 0
    assert features.weighted_slope_10d > 0
    assert features.weighted_slope_15d > 0
    assert features.trend_r2_15d > 0.99
    assert features.trend_quality_15d == pytest.approx(
        features.annualized_slope_15d * features.trend_r2_15d
    )


def test_signed_efficiency_ratio_distinguishes_smooth_up_and_down() -> None:
    up = calculate_features(bars([100 + index for index in range(21)]))
    down = calculate_features(bars([120 - index for index in range(21)]))
    flat = calculate_features(bars([100.0] * 21))
    assert up and down and flat
    assert up.signed_efficiency_ratio_10d == pytest.approx(1)
    assert down.signed_efficiency_ratio_10d == pytest.approx(-1)
    assert flat.signed_efficiency_ratio_10d == 0
    assert down.trend_quality_15d < 0


def test_features_are_point_in_time_and_ignore_future_bars() -> None:
    history = bars([100 * math.exp(index * 0.004) for index in range(22)])
    as_of = calculate_features(history[:21])
    with_future_available = calculate_features(history[:21])
    assert as_of == with_future_available
    assert as_of != calculate_features(history)


@pytest.mark.parametrize("highest", [True, False])
def test_general_ranking_handles_invalid_values_ties_and_direction(highest: bool) -> None:
    rows = [
        {"code": "B", "x": 2},
        {"code": "A", "x": 2},
        {"code": "C", "x": 1},
        {"code": "N", "x": None},
        {"code": "I", "x": float("inf")},
    ]
    result = {row["code"]: row for row in rank_feature(rows, "x", highest_is_best=highest)}
    assert result["A"]["rank_x"] == result["B"]["rank_x"]
    assert result["N"]["rank_x"] is None and result["I"]["rank_x"] is None
    assert rank_feature([{"code": "A", "x": 1}], "x")[0]["pct_rank_x"] == 100


def factor_row(**overrides: float) -> dict[str, float]:
    row = {
        "pct_rank_3d": 100,
        "pct_rank_5d": 80,
        "pct_rank_10d": 60,
        "pct_rank_20d": 40,
        "pct_rank_trend_quality_15d": 80,
        "rs_5d": 0.025,
        "rs_10d": 0.04,
        "rs_20d": 0.06,
        "pct_rank_momentum_acceleration_3d": 90,
        "pct_rank_momentum_acceleration_5d": 70,
        "pct_rank_trend_acceleration": 50,
        "pct_rank_signed_efficiency_ratio_10d": 60,
    }
    row.update(overrides)
    return row


def test_factor_and_composite_scores_follow_fast_rotation_weights() -> None:
    scores = calculate_factor_scores(factor_row())
    assert scores["momentum_strength_score"] == pytest.approx(77)
    assert scores["relative_strength_score"] == pytest.approx(75)
    assert scores["acceleration_score"] == pytest.approx(73)
    expected = 77 * 0.30 + 75 * 0.25 + 73 * 0.25 + 80 * 0.15 + 60 * 0.05
    assert scores["composite_score"] == pytest.approx(expected)
    assert "risk_adjusted_score" not in scores


@pytest.mark.parametrize(
    ("window", "excess_return"),
    [(5, 0.05), (10, 0.08), (20, 0.12)],
)
def test_rs5_rs10_rs20_ranges_keep_benchmark_parity_at_fifty(window: int, excess_return: float) -> None:
    score_range = DEFAULT_CONFIG.relative_strength_score_ranges[window]
    assert map_relative_strength_score(0, score_range) == 50
    assert map_relative_strength_score(excess_return, score_range) == 100
    assert map_relative_strength_score(-excess_return, score_range) == 0


@pytest.mark.parametrize(
    ("ret_5d", "slope", "ma10", "eligible"),
    [(0.01, 0.01, -0.01, True), (0.01, -0.01, 0.01, True), (-0.01, 0.01, 0.01, True),
     (0.01, -0.01, -0.01, False)],
)
def test_absolute_trend_requires_two_of_three_fast_conditions(
    ret_5d: float, slope: float, ma10: float, eligible: bool
) -> None:
    assert is_absolute_trend_eligible(
        {"ret_5d": ret_5d, "weighted_slope_10d": slope, "ma10_ratio": ma10}
    ) is eligible


def test_regime_uses_fast_breadth_and_benchmark_confirmation() -> None:
    benchmark = {"reference_price": 100, "ret_5d": 0.02, "ma10_ratio": 0.01, "weighted_slope_10d": 0.002}
    risk_on = calculate_market_regime(
        [{"ret_5d": 0.01, "ma10_ratio": 0.01}] * 6 + [{"ret_5d": -0.01, "ma10_ratio": -0.01}] * 4,
        benchmark,
        market="CN",
        trade_date=date(2026, 8, 28),
        benchmark_code="510300.SH",
    )
    assert risk_on["regime"] == "RISK_ON"
    assert risk_on["positive_5d_breadth"] == pytest.approx(0.6)
    risk_off = calculate_market_regime(
        [{"ret_5d": -0.01, "ma10_ratio": -0.01}] * 8 + [{"ret_5d": 0.01, "ma10_ratio": 0.01}] * 2,
        {**benchmark, "ret_5d": -0.02, "weighted_slope_10d": -0.002},
        market="US",
        trade_date=date(2026, 8, 28),
        benchmark_code="SPY.US",
    )
    assert risk_off["regime"] == "RISK_OFF"


def candidate(code: str, rank: int, score: float, **overrides) -> dict:
    row = {
        "code": code,
        "rank": rank,
        "rank_5d": rank,
        "composite_score": score,
        "entry_score": score,
        "state": "TRENDING",
        "risk_group": code,
        "absolute_trend_eligible": True,
        "liquidity_eligible": True,
        "relative_strength_ready": True,
        "acceleration_score": 65,
        "ret_3d": 0.01,
        "ret_5d": 0.01,
        "rank_change_1d": 0,
    }
    row.update(overrides)
    return row


def test_top4_entry_top6_hold_and_fast_exit_rules() -> None:
    rows = [
        candidate("NEW", 4, 72, entry_score=70, state="EMERGING"),
        candidate("FIFTH", 5, 90, entry_score=90),
        candidate("HOLD", 6, 60, acceleration_score=40),
        candidate("DETERIORATING", 2, 80, acceleration_score=34, ret_3d=-0.01, ret_5d=0.01),
        candidate("COLLAPSE", 3, 80, acceleration_score=39, rank_change_1d=-4),
    ]
    previous = {"HOLD", "DETERIORATING", "COLLAPSE"}
    selected = select_candidates(rows, previous_candidate_codes=previous)
    assert selected == ["HOLD", "NEW"]
    actions = {row["code"]: public_rotation_action(row, set(selected), previous) for row in rows}
    assert actions["NEW"] == "BUY"
    assert actions["HOLD"] == "HOLD"
    assert actions["DETERIORATING"] == actions["COLLAPSE"] == "EXIT"
    assert actions["FIFTH"] == "WATCH"


def test_entry_rejects_cooling_exhausted_and_weak_states() -> None:
    rows = [candidate(state, 1, 90, state=state) for state in ("COOLING", "EXHAUSTED", "WEAK")]
    assert select_candidates(rows) == []


def test_emerging_classification_detects_new_strength_before_high_composite() -> None:
    row = candidate(
        "NEW",
        4,
        62,
        rank_change_3d=5,
        acceleration_score=72,
        rs_10d_score=65,
        weighted_slope_10d=0.01,
        trend_acceleration=0.01,
        trend_quality_score=55,
        ret_1d=0.01,
        ma20_ratio=0.01,
    )
    assert classify_state(row, 62) == "EMERGING"


def test_rank_change_sign_is_historical_minus_current() -> None:
    assert calculate_rank_changes(3, {1: 7, 3: 2, 5: 3}) == {
        "rank_change_1d": 4,
        "rank_change_3d": -1,
        "rank_change_5d": 0,
    }


def test_candidate_correlation_uses_twenty_point_in_time_returns() -> None:
    base = bars([100 + index + (index % 3) for index in range(21)])
    same = [
        DailyBar(item.trade_date, item.close * 2, item.volume, item.amount)
        for item in base
    ]
    assert DEFAULT_CONFIG.correlation_window == 20
    assert rolling_correlations({"A": base, "B": same})[("A", "B")] == pytest.approx(1)
    assert rolling_correlations({"A": base[:-1], "B": same[:-1]})[("A", "B")] is None


def test_new_hotspot_outranks_stale_old_leader() -> None:
    old = calculate_factor_scores(factor_row(
        pct_rank_3d=20,
        pct_rank_5d=30,
        pct_rank_10d=55,
        pct_rank_20d=100,
        rs_5d=-0.01,
        rs_10d=0.0,
        rs_20d=0.10,
        pct_rank_momentum_acceleration_3d=10,
        pct_rank_momentum_acceleration_5d=15,
        pct_rank_trend_acceleration=20,
    ))
    new = calculate_factor_scores(factor_row(
        pct_rank_3d=100,
        pct_rank_5d=95,
        pct_rank_10d=85,
        pct_rank_20d=50,
        rs_5d=0.05,
        rs_10d=0.08,
        rs_20d=0.02,
        pct_rank_momentum_acceleration_3d=100,
        pct_rank_momentum_acceleration_5d=95,
        pct_rank_trend_acceleration=90,
    ))
    assert new["composite_score"] > old["composite_score"]
    selection = select_candidates([
        candidate("NEW", 1, float(new["composite_score"]), entry_score=80, state="EMERGING"),
        candidate("OLD", 7, float(old["composite_score"]), acceleration_score=20, ret_3d=-0.01),
    ], previous_candidate_codes={"OLD"})
    assert selection == ["NEW"]


def test_dual_market_benchmarks_and_config_validation() -> None:
    assert DEFAULT_CONFIG.benchmark_codes == {"CN": "510300.SH", "US": "SPY.US"}
    with pytest.raises(ValueError, match="momentum_weights"):
        ETFRotationConfig(momentum_weights={3: 0.5})
    with pytest.raises(ValueError, match="entry_rank_threshold"):
        replace(DEFAULT_CONFIG, entry_rank_threshold=7)

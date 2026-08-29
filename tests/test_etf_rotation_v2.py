from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta

import pytest

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig
from finance_analysis.etf_rotation.features import calculate_features
from finance_analysis.etf_rotation.models import DailyBar
from finance_analysis.etf_rotation.ranking import rank_feature
from finance_analysis.etf_rotation.regime import calculate_market_regime
from finance_analysis.etf_rotation.scoring import calculate_factor_scores
from finance_analysis.etf_rotation.selector import public_rotation_action, select_candidates


def bars(closes: list[float]) -> list[DailyBar]:
    return [DailyBar(date(2026, 1, 1) + timedelta(days=i), close, 1000, 100_000_000) for i, close in enumerate(closes)]


def test_smooth_noisy_down_flat_and_jump_features() -> None:
    smooth = calculate_features(bars([100 * math.exp(i * 0.004) for i in range(61)]))
    noisy_closes = [100 * math.exp(i * 0.004 + (0.035 if i % 2 else -0.035)) for i in range(61)]
    noisy = calculate_features(bars(noisy_closes))
    down = calculate_features(bars([160 - i for i in range(61)]))
    flat = calculate_features(bars([100.0] * 61))
    jump = calculate_features(bars([100.0] * 45 + [115.0] * 16))
    assert all(item is not None for item in (smooth, noisy, down, flat, jump))
    assert smooth.weighted_slope_25d > 0 and smooth.trend_r2_25d > 0.99 and smooth.efficiency_ratio_20d > 0.99
    assert noisy.weighted_slope_25d > 0
    assert noisy.trend_r2_25d < smooth.trend_r2_25d
    assert noisy.efficiency_ratio_20d < smooth.efficiency_ratio_20d
    assert down.weighted_slope_25d < 0
    assert flat.weighted_slope_25d == pytest.approx(0) and flat.efficiency_ratio_20d == 0
    assert math.isfinite(flat.risk_adjusted_momentum_60d)
    assert jump.trend_r2_25d < smooth.trend_r2_25d


@pytest.mark.parametrize("highest", [True, False])
def test_general_ranking_handles_invalid_values_ties_and_direction(highest: bool) -> None:
    rows = [{"code": "B", "x": 2}, {"code": "A", "x": 2}, {"code": "C", "x": 1},
            {"code": "N", "x": None}, {"code": "I", "x": float("inf")}, {"code": "Q", "x": float("nan")}]
    result = {row["code"]: row for row in rank_feature(rows, "x", highest_is_best=highest)}
    expected_best = "B" if highest else "C"
    assert result[expected_best]["pct_rank_x"] == (75 if highest else 100)
    assert result["A"]["rank_x"] == result["B"]["rank_x"]
    assert result["N"]["rank_x"] is None and result["I"]["rank_x"] is None and result["Q"]["rank_x"] is None
    assert rank_feature([], "x") == []
    assert rank_feature([{"code": "A", "x": 1}], "x")[0]["pct_rank_x"] == 100


def test_factor_and_composite_scores_follow_configuration() -> None:
    row = {"pct_rank_5d": 100, "pct_rank_20d": 80, "pct_rank_30d": 60, "pct_rank_60d": 40,
           "pct_rank_trend_quality_25d": 90, "pct_rank_rs_20d": 80, "pct_rank_rs_60d": 70,
           "pct_rank_trend_acceleration": 60, "pct_rank_momentum_acceleration": 40,
           "pct_rank_efficiency_ratio_20d": 85, "pct_rank_risk_adjusted_momentum_60d": 75,
           "pct_rank_max_drawdown_60d": 65}
    scores = calculate_factor_scores(row)
    assert scores["momentum_strength_score"] == pytest.approx(60)
    assert scores["relative_strength_score"] == pytest.approx(74)
    assert scores["acceleration_score"] == pytest.approx(55)
    assert scores["risk_adjusted_score"] == pytest.approx(73)
    expected = 60 * .30 + 90 * .25 + 74 * .20 + 55 * .10 + 85 * .10 + 73 * .05
    assert scores["composite_score"] == pytest.approx(expected)
    assert all(value is None or 0 <= value <= 100 for value in scores.values())


def test_regime_classifies_risk_on_neutral_and_risk_off() -> None:
    benchmark = {"reference_price": 100, "ma20_ratio": .05, "ma60_ratio": .10, "weighted_slope_25d": .002}
    risk_on = calculate_market_regime([{"ma20_ratio": .1, "ma60_ratio": .05}] * 10, benchmark,
                                      market="CN", trade_date=date(2026, 8, 28), benchmark_code="510300.SH")
    assert risk_on["regime"] == "RISK_ON" and risk_on["breadth_above_ma60"] == 1
    off_benchmark = {**benchmark, "ma20_ratio": -.05, "ma60_ratio": -.10, "weighted_slope_25d": -.002}
    risk_off = calculate_market_regime([{"ma20_ratio": -.1, "ma60_ratio": -.05}] * 10, off_benchmark,
                                       market="CN", trade_date=date(2026, 8, 28), benchmark_code="510300.SH")
    assert risk_off["regime"] == "RISK_OFF"
    neutral = calculate_market_regime([{"ma20_ratio": .1, "ma60_ratio": .05}] * 5 +
                                      [{"ma20_ratio": -.1, "ma60_ratio": -.05}] * 5, benchmark,
                                      market="CN", trade_date=date(2026, 8, 28), benchmark_code="510300.SH")
    assert neutral["regime"] == "NEUTRAL"


def candidate(code: str, rank: int, score: float, group: str = "G") -> dict:
    return {"code": code, "rank": rank, "rank_5d": rank, "composite_score": score, "entry_score": score,
            "state": "STRONG", "risk_group": group, "absolute_trend_eligible": True,
            "liquidity_eligible": True, "relative_strength_ready": True}


def test_public_hysteresis_and_correlation_are_deterministic() -> None:
    config = replace(DEFAULT_CONFIG, max_per_risk_group=5)
    rows = [candidate("A", 1, 90), candidate("B", 2, 88), candidate("OLD", 8, 65), candidate("DROP", 11, 80)]
    correlations = {("A", "B"): .90}
    selected = select_candidates(rows, config, previous_candidate_codes={"OLD", "DROP"}, correlations=correlations)
    assert selected == ["A", "OLD"]
    assert public_rotation_action("A", set(selected), {"OLD", "DROP"}) == "BUY"
    assert public_rotation_action("OLD", set(selected), {"OLD", "DROP"}) == "HOLD"
    assert public_rotation_action("DROP", set(selected), {"OLD", "DROP"}) == "EXIT"
    assert public_rotation_action("B", set(selected), {"OLD", "DROP"}) == "WATCH"
    assert select_candidates(rows, config, previous_candidate_codes=set(), regime="RISK_OFF") == []


def test_config_validation_fails_early() -> None:
    with pytest.raises(ValueError, match="momentum_weights"):
        ETFRotationConfig(momentum_weights={5: .5})
    with pytest.raises(ValueError, match="entry_rank"):
        replace(DEFAULT_CONFIG, entry_rank=11, hold_rank=10)
    with pytest.raises(ValueError, match="max_candidate_correlation"):
        replace(DEFAULT_CONFIG, max_candidate_correlation=1.1)

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
from finance_analysis.etf_rotation.scoring import calculate_factor_scores, map_relative_strength_score
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
           "pct_rank_trend_quality_25d": 90, "rs_20d": .06, "rs_60d": .08,
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


@pytest.mark.parametrize(
    ("excess_return", "score"),
    [(-.15, 0), (-.05, 25), (0, 50), (.05, 75), (.15, 100)],
)
def test_relative_strength_score_maps_absolute_excess_return(excess_return: float, score: float) -> None:
    assert map_relative_strength_score(excess_return, .10) == pytest.approx(score)


def test_relative_strength_score_does_not_reuse_momentum_percentiles() -> None:
    shared = {
        "pct_rank_5d": 50,
        "pct_rank_20d": 50,
        "pct_rank_30d": 50,
        "pct_rank_60d": 50,
        "pct_rank_trend_quality_25d": 50,
        "pct_rank_trend_acceleration": 50,
        "pct_rank_momentum_acceleration": 50,
        "pct_rank_efficiency_ratio_20d": 50,
        "pct_rank_risk_adjusted_momentum_60d": 50,
        "pct_rank_max_drawdown_60d": 50,
    }
    benchmark_parity = calculate_factor_scores({**shared, "rs_20d": 0, "rs_60d": 0})
    outperformer = calculate_factor_scores({**shared, "rs_20d": .10, "rs_60d": .20})
    underperformer = calculate_factor_scores({**shared, "rs_20d": -.02, "rs_60d": -.04})
    assert benchmark_parity["relative_strength_score"] == pytest.approx(50)
    assert outperformer["relative_strength_score"] == pytest.approx(100)
    assert underperformer["relative_strength_score"] < 50

    changed_percentiles = calculate_factor_scores({
        **shared,
        "pct_rank_20d": 100,
        "pct_rank_60d": 100,
        "pct_rank_rs_20d": 0,
        "pct_rank_rs_60d": 0,
        "rs_20d": 0,
        "rs_60d": 0,
    })
    assert changed_percentiles["relative_strength_score"] == benchmark_parity["relative_strength_score"]
    assert changed_percentiles["momentum_strength_score"] > benchmark_parity["momentum_strength_score"]


def test_relative_strength_score_orders_actual_excess_returns_against_benchmark() -> None:
    benchmark_return = .10
    excess_returns = {
        "A": .20 - benchmark_return,
        "B": .12 - benchmark_return,
        "C": .10 - benchmark_return,
        "D": .05 - benchmark_return,
    }
    scores = {
        code: map_relative_strength_score(excess_return, DEFAULT_CONFIG.relative_strength_score_ranges[20])
        for code, excess_return in excess_returns.items()
    }
    assert scores["A"] > scores["B"] > scores["C"] > scores["D"]
    assert scores["C"] == pytest.approx(50)


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


def candidate(
    code: str,
    rank: int,
    score: float,
    group: str = "G",
    *,
    entry_score: float | None = None,
    state: str = "STRONG",
    absolute_trend: bool = True,
    liquidity: bool = True,
) -> dict:
    return {
        "code": code,
        "rank": rank,
        "rank_5d": rank,
        "composite_score": score,
        "entry_score": score if entry_score is None else entry_score,
        "state": state,
        "risk_group": group,
        "absolute_trend_eligible": absolute_trend,
        "liquidity_eligible": liquidity,
        "relative_strength_ready": True,
    }


def test_public_hysteresis_and_correlation_are_deterministic() -> None:
    config = replace(DEFAULT_CONFIG, max_per_risk_group=5)
    rows = [candidate("A", 1, 90), candidate("B", 2, 88), candidate("OLD", 8, 65), candidate("DROP", 11, 80)]
    correlations = {("A", "B"): .90}
    selected = select_candidates(rows, config, previous_candidate_codes={"OLD", "DROP"}, correlations=correlations)
    by_code = {row["code"]: row for row in rows}
    assert selected == ["OLD", "A"]
    assert public_rotation_action(by_code["A"], set(selected), {"OLD", "DROP"}) == "BUY"
    assert public_rotation_action(by_code["OLD"], set(selected), {"OLD", "DROP"}) == "HOLD"
    assert public_rotation_action(by_code["DROP"], set(selected), {"OLD", "DROP"}) == "EXIT"
    assert public_rotation_action(by_code["B"], set(selected), {"OLD", "DROP"}) == "WATCH"
    assert select_candidates(rows, config, previous_candidate_codes=set(), regime="RISK_OFF") == []


def test_valid_holds_have_priority_over_stronger_new_entries_when_full() -> None:
    config = replace(DEFAULT_CONFIG, max_candidates=2, max_per_risk_group=5)
    rows = [candidate("OLD1", 7, 65), candidate("OLD2", 8, 64), candidate("NEW", 1, 99)]
    selected = select_candidates(rows, config, previous_candidate_codes={"OLD1", "OLD2"})
    assert selected == ["OLD1", "OLD2"]
    assert public_rotation_action(rows[0], set(selected), {"OLD1", "OLD2"}) == "HOLD"
    assert public_rotation_action(rows[1], set(selected), {"OLD1", "OLD2"}) == "HOLD"
    assert public_rotation_action(rows[2], set(selected), {"OLD1", "OLD2"}) == "WATCH"


def test_excess_valid_holds_are_truncated_deterministically_with_diagnostic() -> None:
    config = replace(DEFAULT_CONFIG, max_candidates=2, max_per_risk_group=5)
    rows = [candidate("B", 8, 65), candidate("C", 7, 64), candidate("A", 7, 65)]
    diagnostics: list[str] = []
    selected = select_candidates(
        rows,
        config,
        previous_candidate_codes={"A", "B", "C"},
        diagnostics=diagnostics,
    )
    assert selected == ["A", "B"]
    assert diagnostics and "valid holds exceed candidate limit" in diagnostics[0]


def test_holds_survive_regime_and_new_entries_respect_held_diversification() -> None:
    config = replace(DEFAULT_CONFIG, max_candidates=3, max_per_risk_group=1)
    held = candidate("HELD", 7, 65, group="X")
    same_group = candidate("SAME_GROUP", 1, 99, group="X")
    correlated = candidate("CORRELATED", 2, 98, group="Y")
    independent = candidate("INDEPENDENT", 3, 97, group="Z")
    rows = [same_group, correlated, independent, held]
    correlations = {("CORRELATED", "HELD"): .90, ("HELD", "INDEPENDENT"): .20}
    selected = select_candidates(
        rows,
        config,
        previous_candidate_codes={"HELD"},
        correlations=correlations,
    )
    assert selected == ["HELD", "INDEPENDENT"]
    assert select_candidates(rows, config, previous_candidate_codes={"HELD"}, regime="RISK_OFF") == ["HELD"]


def test_entry_score_controls_buy_but_not_hold() -> None:
    config = replace(DEFAULT_CONFIG, max_per_risk_group=5)
    buy = candidate("BUY", 3, 80, entry_score=82)
    delayed = candidate("DELAY", 2, 80, entry_score=68)
    held = candidate("HELD", 8, 65, entry_score=20, state="EXHAUSTED")
    selected = select_candidates([buy, delayed, held], config, previous_candidate_codes={"HELD"})
    assert selected == ["HELD", "BUY"]
    assert public_rotation_action(buy, set(selected), {"HELD"}) == "BUY"
    assert public_rotation_action(delayed, set(selected), {"HELD"}) == "WATCH"
    assert public_rotation_action(held, set(selected), {"HELD"}) == "HOLD"


@pytest.mark.parametrize(
    "row",
    [
        candidate("LOW", 6, 54),
        candidate("WEAK", 6, 70, state="WEAK"),
        candidate("NO_TREND", 6, 70, absolute_trend=False),
        candidate("ILLIQUID", 6, 70, liquidity=False),
    ],
)
def test_watch_requires_threshold_and_basic_eligibility(row: dict) -> None:
    assert public_rotation_action(row, set(), set()) is None
    watch = candidate("WATCH", 6, DEFAULT_CONFIG.watch_composite_threshold)
    assert public_rotation_action(watch, set(), set()) == "WATCH"


def test_public_rotation_action_integration() -> None:
    rows = [
        candidate("OLD_A", 7, 68),
        candidate("OLD_B", 12, 55),
        candidate("NEW_C", 2, 90, entry_score=85),
        candidate("WEAK_D", 20, 20, state="WEAK"),
    ]
    previous = {"OLD_A", "OLD_B"}
    selected = set(select_candidates(rows, previous_candidate_codes=previous))
    actions = {row["code"]: public_rotation_action(row, selected, previous) for row in rows}
    assert actions == {"OLD_A": "HOLD", "OLD_B": "EXIT", "NEW_C": "BUY", "WEAK_D": None}


def test_config_validation_fails_early() -> None:
    with pytest.raises(ValueError, match="momentum_weights"):
        ETFRotationConfig(momentum_weights={5: .5})
    with pytest.raises(ValueError, match="entry_rank_threshold"):
        replace(DEFAULT_CONFIG, entry_rank_threshold=11, hold_rank_threshold=10)
    with pytest.raises(ValueError, match="max_candidate_correlation"):
        replace(DEFAULT_CONFIG, max_candidate_correlation=1.1)

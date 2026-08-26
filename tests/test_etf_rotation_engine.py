from __future__ import annotations

from datetime import date, timedelta

import pytest

from finance_analysis.etf_rotation.classifier import STATE_PRIORITY, classify_state
from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig
from finance_analysis.etf_rotation.features import calculate_features
from finance_analysis.etf_rotation.models import DailyBar
from finance_analysis.etf_rotation.ranking import calculate_rank_changes, rank_cross_section
from finance_analysis.etf_rotation.readiness import ETFRotationReadinessError, require_minimum_coverage
from finance_analysis.etf_rotation.scoring import (
    calculate_entry_score,
    calculate_momentum_score,
    ma20_overextension_penalty,
)
from finance_analysis.etf_rotation.selector import select_candidates


def _bars(closes: list[float]) -> list[DailyBar]:
    start = date(2026, 1, 1)
    return [
        DailyBar(start + timedelta(days=index), close, 100 + index, 1000 + index)
        for index, close in enumerate(closes)
    ]


def test_return_previous_return_acceleration_and_secondary_features() -> None:
    closes = [100.0 + index for index in range(61)]
    features = calculate_features(_bars(closes))
    assert features is not None
    for window in (1, 5, 10, 20, 30, 60):
        assert getattr(features, f"ret_{window}d") == pytest.approx(160 / (160 - window) - 1)
    assert features.previous_5d_return == pytest.approx(155 / 150 - 1)
    assert features.momentum_acceleration == pytest.approx((160 / 155 - 1) - (155 / 150 - 1))
    assert features.ma20_ratio == pytest.approx(160 / sum(closes[-20:]) * 20 - 1)
    assert features.ma60_ratio == pytest.approx(160 / sum(closes[-60:]) * 60 - 1)
    volumes = [100 + index for index in range(41, 61)]
    assert features.volume_ratio_5d == pytest.approx((sum(volumes[-5:]) / 5) / (sum(volumes) / 20))
    assert features.avg_amount_20d == pytest.approx(sum(1000 + index for index in range(41, 61)) / 20)
    assert features.realized_vol_20d > 0
    assert features.distance_from_20d_high == 0


def test_late_listed_etf_is_not_rankable() -> None:
    assert calculate_features(_bars([100.0] * 60)) is None


def test_percentile_ranking_and_ties_are_deterministic() -> None:
    rows = [
        {"code": "A", **{f"ret_{window}d": 3.0 for window in (1, 5, 10, 20, 30, 60)}},
        {"code": "B", **{f"ret_{window}d": 2.0 for window in (1, 5, 10, 20, 30, 60)}},
        {"code": "C", **{f"ret_{window}d": 2.0 for window in (1, 5, 10, 20, 30, 60)}},
        {"code": "D", **{f"ret_{window}d": 1.0 for window in (1, 5, 10, 20, 30, 60)}},
    ]
    ranked = {row["code"]: row for row in rank_cross_section(rows)}
    assert ranked["A"]["rank_5d"] == 1
    assert ranked["A"]["pct_rank_5d"] == 100
    assert ranked["B"]["rank_5d"] == ranked["C"]["rank_5d"] == 2
    assert ranked["B"]["pct_rank_5d"] == ranked["C"]["pct_rank_5d"] == 50
    assert ranked["D"]["rank_5d"] == 4
    assert ranked["D"]["pct_rank_5d"] == 0


def test_rank_change_direction_and_missing_history() -> None:
    assert calculate_rank_changes(6, {5: 28}) == {
        "rank_change_1d": None,
        "rank_change_3d": None,
        "rank_change_5d": 22,
    }
    assert calculate_rank_changes(6, {})["rank_change_5d"] is None


def test_momentum_score_uses_percentiles() -> None:
    row = {"pct_rank_5d": 100, "pct_rank_10d": 80, "pct_rank_30d": 60, "pct_rank_60d": 40}
    assert calculate_momentum_score(row) == pytest.approx(78)


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(0.049999, 0), (0.05, -2), (0.099999, -2), (0.10, -5), (0.149999, -5), (0.15, -10)],
)
def test_ma20_penalty_boundaries(ratio: float, expected: float) -> None:
    assert ma20_overextension_penalty(ratio) == expected


def test_entry_score_all_independent_components_and_overheat() -> None:
    base = {
        "ret_1d": 0.02,
        "momentum_acceleration": 0.02,
        "rank_change_5d": 10,
        "volume_ratio_5d": 1.2,
        "ma20_ratio": 0.10,
    }
    score, components = calculate_entry_score(base, 70)
    assert components == {
        "base_momentum": 70.0,
        "daily_confirmation": 3.0,
        "acceleration": 5.0,
        "rank_improvement": 5.0,
        "volume_confirmation": 2.0,
        "ma20_penalty": -5.0,
        "daily_overheat_penalty": 0.0,
    }
    assert score == 80

    strong = {**base, "momentum_acceleration": 0.05}
    assert calculate_entry_score(strong, 70)[1]["acceleration"] == 8
    overheated = {**base, "ret_1d": 0.060001}
    overheat_components = calculate_entry_score(overheated, 70)[1]
    assert overheat_components["daily_confirmation"] == 0
    assert overheat_components["daily_overheat_penalty"] == -5


def _state_row(**updates):
    row = {
        "ret_1d": 0.0,
        "ma20_ratio": 0.0,
        "momentum_acceleration": 0.01,
        "rank_change_5d": 0,
        "rank_5d": 20,
        "pct_rank_5d": 50,
        "pct_rank_10d": 50,
        "pct_rank_30d": 50,
    }
    row.update(updates)
    return row


def test_state_classification_and_priority() -> None:
    assert STATE_PRIORITY == ("EXHAUSTED", "COOLING", "EMERGING", "STRONG", "TRENDING", "WEAK", "NEUTRAL")
    assert classify_state(_state_row(), 30) == "WEAK"
    assert classify_state(_state_row(), 85) == "STRONG"
    assert classify_state(_state_row(pct_rank_5d=85, pct_rank_10d=75, pct_rank_30d=65), 70) == "TRENDING"
    assert classify_state(_state_row(rank_5d=6, rank_change_5d=22), 65) == "EMERGING"
    assert classify_state(_state_row(momentum_acceleration=-0.01, rank_change_5d=-2), 75) == "COOLING"
    assert classify_state(_state_row(), 55) == "NEUTRAL"
    # EXHAUSTED wins over STRONG and EMERGING; COOLING wins over EMERGING.
    assert classify_state(_state_row(ret_1d=0.07, rank_5d=1, rank_change_5d=20), 90) == "EXHAUSTED"
    assert classify_state(
        _state_row(momentum_acceleration=-0.01, rank_5d=1, rank_change_5d=-1), 75
    ) == "COOLING"


def test_candidate_risk_groups_and_deterministic_ordering() -> None:
    rows = [
        {"code": "B", "state": "STRONG", "entry_score": 90, "momentum_score": 80, "rank_5d": 2, "risk_group": "X"},
        {"code": "A", "state": "STRONG", "entry_score": 90, "momentum_score": 80, "rank_5d": 2, "risk_group": "X"},
        {"code": "C", "state": "TRENDING", "entry_score": 89, "momentum_score": 85, "rank_5d": 1, "risk_group": "X"},
        {"code": "D", "state": "EXHAUSTED", "entry_score": 99, "momentum_score": 99, "rank_5d": 1, "risk_group": "Y"},
        {"code": "E", "state": "NEUTRAL", "entry_score": 80, "momentum_score": 70, "rank_5d": 3, "risk_group": "Y"},
        {"code": "F", "state": "WEAK", "entry_score": 95, "momentum_score": 20, "rank_5d": 4, "risk_group": "Z"},
    ]
    assert select_candidates(rows) == ["A", "B", "E"]


def test_coverage_thresholds() -> None:
    assert require_minimum_coverage(label="daily", available=39, expected=40, minimum=0.95)[0] == pytest.approx(0.975)
    assert require_minimum_coverage(label="rankable", available=38, expected=40, minimum=0.95)[0] == pytest.approx(0.95)
    with pytest.raises(ETFRotationReadinessError, match="below"):
        require_minimum_coverage(label="daily", available=35, expected=40, minimum=0.95)
    with pytest.raises(ETFRotationReadinessError, match="below"):
        require_minimum_coverage(label="rankable", available=37, expected=40, minimum=0.95)

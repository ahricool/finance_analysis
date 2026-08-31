from __future__ import annotations

from datetime import date, timedelta

import pytest

from finance_analysis.etf_rotation.config import RETURN_WINDOWS  # pragma: allowlist secret
from finance_analysis.etf_rotation.models import DailyBar  # pragma: allowlist secret
from finance_analysis.etf_rotation.ranking import rank_cross_section  # pragma: allowlist secret
from finance_analysis.etf_rotation.readiness import (  # pragma: allowlist secret
    ETFRotationReadinessError,
    require_minimum_coverage,
)
from finance_analysis.etf_rotation.risk import (  # pragma: allowlist secret
    calculate_stop_loss_pct,
    calculate_suggested_stop_price,
)
from finance_analysis.etf_rotation.scoring import (  # pragma: allowlist secret
    calculate_entry_score,
    ma20_overextension_penalty,
)


def _bars(closes: list[float]) -> list[DailyBar]:
    return [
        DailyBar(date(2026, 1, 1) + timedelta(days=index), close, 100 + index, 1000 + index)
        for index, close in enumerate(closes)
    ]


def test_fast_return_ranking_and_ties_are_deterministic() -> None:
    rows = [
        {"code": "A", **{f"ret_{window}d": 3.0 for window in RETURN_WINDOWS}},
        {"code": "B", **{f"ret_{window}d": 2.0 for window in RETURN_WINDOWS}},
        {"code": "C", **{f"ret_{window}d": 2.0 for window in RETURN_WINDOWS}},
        {"code": "D", **{f"ret_{window}d": 1.0 for window in RETURN_WINDOWS}},
    ]
    ranked = {row["code"]: row for row in rank_cross_section(rows)}
    assert ranked["A"]["rank_3d"] == 1
    assert ranked["A"]["pct_rank_3d"] == 100
    assert ranked["B"]["rank_3d"] == ranked["C"]["rank_3d"] == 2
    assert ranked["B"]["pct_rank_3d"] == ranked["C"]["pct_rank_3d"] == 50
    assert set(key for key in ranked["A"] if key.startswith("ret_")) == {
        "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d"
    }


def test_volatility_stop_loss_floor_cap_and_price() -> None:
    assert calculate_stop_loss_pct(0.3175) == pytest.approx(0.05, rel=0.01)
    assert calculate_stop_loss_pct(0.01) == pytest.approx(0.03)
    assert calculate_stop_loss_pct(1.0) == pytest.approx(0.08)
    assert calculate_suggested_stop_price(100, 0.05) == pytest.approx(95)


@pytest.mark.parametrize("ratio,expected", [
    (0.049999, 0), (0.05, -2), (0.099999, -2), (0.10, -5), (0.149999, -5), (0.15, -10),
])
def test_ma20_entry_penalty_boundaries(ratio: float, expected: float) -> None:
    assert ma20_overextension_penalty(ratio) == expected


def test_entry_score_keeps_confirmation_and_overheat_components() -> None:
    row = {"ret_1d": 0.02, "volume_ratio_5d": 1.2, "ma20_ratio": 0.10}
    score, components = calculate_entry_score(row, 70)
    assert score == 69
    assert components == {
        "base_composite": 70.0,
        "daily_confirmation": 2.0,
        "volume_confirmation": 2.0,
        "ma20_penalty": -5.0,
        "daily_overheat_penalty": 0.0,
    }
    assert calculate_entry_score({**row, "ret_1d": 0.07}, 70)[0] == 62


def test_coverage_thresholds() -> None:
    assert require_minimum_coverage(label="daily", available=39, expected=40, minimum=0.95)[0] == pytest.approx(0.975)
    with pytest.raises(ETFRotationReadinessError, match="below"):
        require_minimum_coverage(label="daily", available=35, expected=40, minimum=0.95)

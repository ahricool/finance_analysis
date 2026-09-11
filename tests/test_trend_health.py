from copy import deepcopy
from datetime import date, timedelta

import pytest

from finance_analysis.trend_following.fragility import calculate_fragility
from finance_analysis.trend_following.lifecycle import classify_lifecycle

DAY = date(2026, 9, 1)


def snapshot(**changes):
    result = dict(
        trend_duration_days=13,
        trend_score=90,
        state="HOLDING",
        setup="TREND_RESUME",
        features={
            "health_version": 1,
            "trend_candidate": True,
            "trend_quality": 90,
            "trend_acceleration": 0.2,
            "signed_efficiency_ratio_10d": 0.8,
            "rs_5d": 0.06,
            "rank_percentile": 0.1,
            "distance_from_recent_high": 0,
            "distance_from_ma20": 0.08,
        },
    )
    result.update(changes)
    return result


def history(current):
    return {offset: {**deepcopy(current), "trade_date": DAY - timedelta(days=offset)} for offset in (3, 5)}


@pytest.mark.parametrize("duration,stage", [(2, "IGNITION"), (6, "EMERGING"), (13, "EXPANSION"), (24, "MATURE")])
def test_healthy_lifecycle(duration, stage):
    assert classify_lifecycle(snapshot(trend_duration_days=duration)) == stage


def test_candidate_failure_is_broken_not_a_new_trade_rule():
    current = snapshot()
    current["features"]["trend_candidate"] = False
    assert classify_lifecycle(current) == "BROKEN"
    # EXIT can be a portfolio/risk event while absolute trend still holds.
    assert classify_lifecycle(snapshot(state="EXIT")) == "EXPANSION"


def test_stable_high_strength_has_low_fragility_not_inverse_strength():
    current = snapshot()
    result = calculate_fragility(current, history(current), as_of=DAY)
    assert result["fragility_score"] == 0
    assert result["fragility_score"] != 100 - current["trend_score"]
    current["trend_score"] = 40
    assert calculate_fragility(current, history(current), as_of=DAY)["fragility_score"] == 0


def test_high_strength_can_be_highly_fragile_and_exhausted():
    current = snapshot()
    old = history(current)
    current["features"].update(
        trend_quality=55,
        trend_acceleration=-0.4,
        signed_efficiency_ratio_10d=0.2,
        rs_5d=0.0,
        rank_percentile=0.5,
        distance_from_recent_high=-0.08,
        distance_from_ma20=0.01,
    )
    current.update(calculate_fragility(current, old, as_of=DAY))
    assert current["trend_score"] == 90
    assert current["fragility_score"] > 90
    assert classify_lifecycle(current) == "EXHAUSTION"


def test_missing_components_and_old_versions_are_not_zeros():
    current = snapshot()
    result = calculate_fragility(current, {}, as_of=DAY)
    assert result["fragility_score"] is None
    assert result["fragility_breakdown"]["acceleration_decay"] is None
    old = history(current)
    for row in old.values():
        del row["features"]["health_version"]
    assert calculate_fragility(current, old, as_of=DAY)["fragility_score"] is None


def test_future_and_same_day_snapshots_cannot_supply_baselines():
    current = snapshot()
    old = history(current)
    old[3]["trade_date"] = DAY
    old[5]["trade_date"] = DAY + timedelta(days=1)
    assert calculate_fragility(current, old, as_of=DAY)["fragility_score"] is None


def test_available_component_weights_renormalize():
    current = snapshot()
    old = history(current)
    for row in old.values():
        del row["features"]["rank_percentile"]
        del row["features"]["rs_5d"]
    current["features"]["trend_quality"] = 60
    result = calculate_fragility(current, old, as_of=DAY)
    assert result["fragility_score"] == pytest.approx(100 * 0.2 / 0.7, abs=0.01)
    assert result["fragility_breakdown"]["rank_decay"] is None

from datetime import date, timedelta
from types import SimpleNamespace as Bar

import pytest
from finance_analysis.industry_strength.features import index_features, constituent_observations, breadth
from finance_analysis.industry_strength.scoring import percentiles, rank_rows
from finance_analysis.industry_strength.state import classify

DAYS = [date(2026, 8, 1) + timedelta(days=i) for i in range(21)]


def bars(prices, amounts=None):
    return [Bar(trade_date=d, close=p, amount=a, volume=10) for d, p, a in zip(DAYS, prices, amounts or [100] * 21)]


def test_features_use_sessions_and_decimal_units():
    row = index_features(bars(list(range(100, 121)), [10] * 16 + [20] * 5), bars([100] * 21), DAYS)
    assert row["ret_5d"] == pytest.approx(120 / 115 - 1)
    assert row["ret_10d"] == pytest.approx(120 / 110 - 1)
    assert row["ret_20d"] == pytest.approx(0.2)
    assert row["rs_10d"] == row["ret_10d"]
    assert row["previous_5d_return"] == pytest.approx(115 / 110 - 1)
    assert row["momentum_acceleration_5d"] == pytest.approx(120 / 115 - 115 / 110)
    assert row["turnover_ratio_5d"] == pytest.approx(20 / 12.5)
    benchmark = bars([100] * 20 + [110])
    assert index_features(bars([100] * 20 + [120]), benchmark, DAYS)["rs_5d"] == pytest.approx(0.1)


@pytest.mark.parametrize("bad", ["missing", "duplicate", "zero", "nan", "turnover", "empty"])
def test_features_reject_invalid_windows(bad):
    rows = bars([100] * 21)
    if bad == "missing":
        rows.pop(5)
    if bad == "duplicate":
        rows.append(rows[0])
    if bad == "zero":
        rows[-1].close = 0
    if bad == "nan":
        rows[-1].close = float("nan")
    if bad == "turnover":
        rows[-1].amount = None
    if bad == "empty":
        rows = []
    with pytest.raises(ValueError):
        index_features(rows, bars([100] * 21), DAYS)


def test_breadth_denominator_excludes_stale_and_incomplete_members():
    members = [{"thscode": c, "name": c} for c in ["up", "down", "flat", "missing", "stale", "ipo"]]
    prices = {
        "up": bars([100] * 20 + [110]),
        "down": bars([100] * 20 + [90]),
        "flat": bars([100] * 21),
        "stale": bars([100] * 21)[:-1],
        "ipo": bars([100] * 21)[-3:],
    }
    observations = constituent_observations(members, prices, DAYS)
    row = breadth(observations)
    assert row["constituent_count"] == 6 and row["valid_constituent_count"] == 3
    assert row["up_count"] == row["down_count"] == row["flat_count"] == 1
    assert row["up_ratio"] == row["above_ma5_ratio"] == row["above_ma20_ratio"] == pytest.approx(1 / 3)
    assert row["equal_weight_return"] == pytest.approx(0)
    assert observations[0]["code"] == "up"
    assert breadth([])["up_ratio"] is None


def test_ranking_direction_weight_ties_and_exact_session_deltas():
    assert percentiles([1, 2, 2, 4]) == [0, 50, 50, 100]
    assert percentiles([1]) == [50]
    rows = [
        {"industry_code": c, "rs_5d": n, "rs_10d": n, "rs_20d": n, "momentum_acceleration_5d": n}
        for c, n in [("B", 1), ("C", 2), ("A", 2)]
    ]
    history = {
        (DAYS[-2], "A"): {"strength_rank": 7},
        (DAYS[-4], "A"): {"strength_rank": 10},
        (DAYS[-6], "A"): {"strength_rank": 2},
    }
    rank_rows(rows, history, DAYS[:-1])
    assert [r["industry_code"] for r in rows] == ["A", "C", "B"]
    assert rows[0]["strength_rank"] == 1 and rows[0]["strength_score"] == pytest.approx(75)
    assert rows[0]["rs_5d_rank"] == 1
    assert [rows[0][f"rank_change_{n}d"] for n in (1, 3, 5)] == [6, 9, 1]
    assert rows[1]["rank_change_1d"] is None
    weighted = [
        {"industry_code": "A", "rs_5d": 2, "rs_10d": 0, "rs_20d": 2, "momentum_acceleration_5d": 0},
        {"industry_code": "B", "rs_5d": 1, "rs_10d": 1, "rs_20d": 1, "momentum_acceleration_5d": 0},
    ]
    rank_rows(weighted, {}, DAYS[:-1])
    assert weighted[0]["strength_score"] == pytest.approx(65)


@pytest.mark.parametrize(
    "state,updates,previous",
    [
        ("EMERGING", {"rank_change_3d": 8, "acceleration_percentile": 95}, None),
        ("STRONG", {"strength_score": 90, "strength_rank": 1}, {"strength_score": 85}),
        ("COOLING", {"strength_score": 90, "momentum_acceleration_5d": -0.01}, {"strength_score": 90}),
        ("WEAK", {"strength_score": 10, "rs_5d": -0.1, "rs_10d": -0.1, "up_ratio": 0.2, "above_ma20_ratio": 0.2}, None),
        ("NEUTRAL", {}, None),
        ("NEUTRAL", {"strength_score": 95}, None),
    ],
)
def test_deterministic_states(state, updates, previous):
    row = dict(
        strength_score=50,
        strength_rank=1,
        rank_change_3d=0,
        rs_5d=0.1,
        rs_10d=0.1,
        rs_20d=0.1,
        momentum_acceleration_5d=0.01,
        acceleration_percentile=50,
        turnover_ratio_5d=1.1,
        up_ratio=0.7,
        above_ma20_ratio=0.7,
    )
    assert classify({**row, **updates}, 20, previous) == state

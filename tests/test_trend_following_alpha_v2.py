"""Alpha V2 curve, path and comparison regressions, entirely offline."""

from dataclasses import replace
from datetime import date, timedelta
import json
import math

import numpy as np
import pytest

from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.features import calculate_features
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.ranking import rank_candidates
from finance_analysis.trend_following.scoring import (
    breakout_quality,
    calculate_alpha_score,
    calculate_breakout_score,
    calculate_path_score,
    calculate_rs_score,
    calculate_trend_score,
    extension_quality,
    sigmoid,
    smoothstep,
    tanh_quality,
)


def path_fixture(kind):
    """Same 20D return; B concentrates gains into two jumps and then swings widely."""
    smooth = [0.012, 0.010, 0.008, -0.003, 0.012] * 4
    jump = [-0.003] * 10 + [0.001, -0.008, 0.001, -0.006, 0.13, 0.12, -0.035, 0.025, -0.03]
    jump.append(np.prod(1 + np.array(smooth)) / np.prod(1 + np.array(jump)) - 1)
    returns = smooth if kind == "smooth" else jump
    closes = [100.0] * 40
    for value in returns:
        closes.append(closes[-1] * (1 + value))
    bars = []
    for index, close in enumerate(closes):
        previous = closes[max(0, index - 1)]
        spread = close * (0.035 if kind == "jump" and index >= 55 else 0.003)
        bars.append(
            DailyBar(
                date(2026, 1, 1) + timedelta(days=index),
                previous,
                max(previous, close) + spread,
                min(previous, close) - spread,
                close,
                1000,
            )
        )
    row = calculate_features(bars)
    row.update(code=kind, rs_5d=row["return_5d"], rs_10d=row["return_10d"], rs_20d=row["return_20d"])
    return row


def scored(**updates):
    row = path_fixture("smooth")
    row.update(updates)
    return rank_candidates([row])[0]


@pytest.mark.parametrize("scale", [0.08, 0.12, 0.18, 0.8])
def test_continuous_helpers_bounds_and_monotonicity(scale):
    xs = np.linspace(-2, 2, 200)
    values = [tanh_quality(x, scale) for x in xs]
    assert values == sorted(values)
    assert all(0 <= value <= 100 for value in values)
    assert tanh_quality(0, scale) == 50
    assert sigmoid(-1000) == 0 and sigmoid(1000) == 1
    assert smoothstep(0.45, 0.45, 0.8) == 0
    assert smoothstep(0.8, 0.45, 0.8) == 1
    assert smoothstep(0.625, 0.45, 0.8) == pytest.approx(0.5)


def test_breakout_is_continuous_at_previous_high_and_not_double_counted():
    assert abs(breakout_quality(1e-6) - breakout_quality(-1e-6)) < 0.001
    assert breakout_quality(-0.2) < breakout_quality(0) < breakout_quality(0.75)
    assert breakout_quality(0.75) > breakout_quality(2) > breakout_quality(4)
    row = path_fixture("smooth")
    row.update(
        previous_high_10=row["reference_price"] - 0.75 * row["atr20"],
        previous_high_20=row["reference_price"] - 0.75 * row["atr20"],
    )
    _, breakdown = calculate_breakout_score(row)
    assert breakdown["breakout_quality"] == pytest.approx(breakout_quality(0.75))
    before = calculate_breakout_score(row)[0]
    row.update(
        breakout_10d=False,
        breakout_20d=False,
        trend_resume=True,
        compression_breakout=True,
        prior_compression=True,
        breakout_distance=100,
        breakout_10d_strength=100,
        breakout_20d_strength=100,
    )
    assert calculate_breakout_score(row)[0] == before


def test_return_and_rs_remain_distinguishable_beyond_old_saturation():
    for scale in (0.08, 0.12, 0.18):
        assert 50 < tanh_quality(0.20, scale) < tanh_quality(0.25, scale) < tanh_quality(0.30, scale) < 100
    row = scored()
    rs = calculate_rs_score(row)[0]
    row.update(return_10d_percentile=0, return_20d_percentile=0)
    assert calculate_rs_score(row)[0] == rs


def test_volume_can_only_contribute_2_25_alpha_points_and_boolean_compression_none():
    low, high = scored(volume_ratio=0), scored(volume_ratio=1000)
    assert 0 < high["alpha_score"] - low["alpha_score"] <= 2.25
    assert scored(prior_compression=False)["alpha_score"] == scored(prior_compression=True)["alpha_score"]


def test_r2_is_linear_and_has_material_trend_alpha_contribution():
    low, high = scored(weighted_r2=0.2), scored(weighted_r2=0.95)
    assert high["trend_score"] - low["trend_score"] == pytest.approx(22.5)
    assert high["alpha_score"] - low["alpha_score"] == pytest.approx(9)
    assert calculate_trend_score(high)[1]["weighted_r2"] == 95


def test_extension_compression_and_path_curves():
    assert extension_quality(-0.02) < extension_quality(0) < extension_quality(0.03) < extension_quality(0.06)
    assert extension_quality(0.08) > extension_quality(0.12) > extension_quality(0.20) > extension_quality(0.30) > 0
    row = path_fixture("smooth")
    compression = [
        calculate_breakout_score({**row, "atr_contraction_ratio": r, "range_contraction_ratio": r})[1][
            "compression_quality"
        ]
        for r in [0.4, 0.6, 0.8, 1, 1.2]
    ]
    assert compression == sorted(compression, reverse=True)
    for key, values in [
        ("positive_return_concentration", [0.3, 0.45, 0.5, 0.65, 0.8, 1]),
        ("atr_expansion_ratio", [1, 1.1, 1.2, 1.5, 2, 3]),
        ("downside_upside_ratio", [0, 0.2, 0.5, 1, 2, 3]),
    ]:
        scores = [calculate_path_score({**row, key: value})[0] for value in values]
        assert scores == sorted(scores, reverse=True)
    for edge in [0.45, 0.8]:
        a = calculate_path_score({**row, "positive_return_concentration": edge - 1e-6})[0]
        b = calculate_path_score({**row, "positive_return_concentration": edge + 1e-6})[0]
        assert abs(a - b) < 0.001


def test_smooth_trend_beats_equal_return_jump_and_debug_v1_is_isolated():
    a, b = path_fixture("smooth"), path_fixture("jump")
    assert a["return_20d"] == pytest.approx(b["return_20d"])
    rows = rank_candidates([a, b], replace(DEFAULT_CONFIG, compare_alpha_v1=True))
    assert rows[0]["code"] == "smooth"
    assert a["path_score"] > b["path_score"] + 30
    # Two-row percentile extremes reward B's steeper recent slope; compare R² at equal slope.
    a_trend = calculate_trend_score({**a, "weighted_slope_percentile": 50})[0]
    b_trend = calculate_trend_score({**b, "weighted_slope_percentile": 50})[0]
    assert a_trend > b_trend
    assert a["alpha_score"] > b["alpha_score"] + 10
    assert a["score_breakdown"]["alpha_v1"]["score"] < b["score_breakdown"]["alpha_v1"]["score"]
    assert a["positive_return_concentration"] < b["positive_return_concentration"]
    assert a["atr_expansion_ratio"] < b["atr_expansion_ratio"]
    for row in rows:
        alpha = row["score_breakdown"]["alpha"]
        assert sum(alpha["contributions"].values()) == pytest.approx(row["alpha_score"], abs=0.0001)
        assert alpha["weights"] == {"trend": 0.4, "rs": 0.25, "setup": 0.15, "path": 0.2}
        assert "alpha_v1" in row["score_breakdown"]
        json.dumps(row, allow_nan=False)
    # Controlling every non-path component still prefers the smooth path.
    controlled = {**b, "trend_score": a["trend_score"], "rs_score": a["rs_score"], "setup_score": a["setup_score"]}
    assert calculate_alpha_score(a)[0] > calculate_alpha_score(controlled)[0]
    assert "alpha_v1" not in scored()["score_breakdown"]


@pytest.mark.parametrize("step", [0, -0.5, 0.5])
def test_no_positive_or_negative_returns_and_zero_atr_are_finite(step):
    bars = [
        DailyBar(
            date(2026, 1, 1) + timedelta(days=i), 100 + i * step, 100 + i * step, 100 + i * step, 100 + i * step, 0
        )
        for i in range(30)
    ]
    row = calculate_features(bars)
    row.update(code="zero", rs_5d=0, rs_10d=0, rs_20d=0)
    ranked = rank_candidates([row])[0]
    json.dumps(ranked, allow_nan=False)
    if step <= 0:
        assert row["positive_return_concentration"] is None
        assert row["downside_upside_ratio"] is None
        assert row["score_breakdown"]["path"]["downside_control_quality"] == 0
    else:
        assert row["downside_upside_ratio"] == 0
        assert row["downside_control_quality"] == 100
    assert math.isfinite(ranked["alpha_score"])


def test_path_features_use_ten_simple_returns_and_compression_excludes_today():
    closes = [100.0] * 30
    for daily_return in [0.01, 0.02, -0.01, 0.03, 0, 0.04, -0.02, 0.01, 0.01, 0.02]:
        closes.append(closes[-1] * (1 + daily_return))
    bars = [
        DailyBar(date(2026, 1, 1) + timedelta(days=i), close, close + 1, close - 1, close, 1000)
        for i, close in enumerate(closes)
    ]
    row = calculate_features(bars)
    assert row["positive_return_concentration"] == pytest.approx(0.5)
    assert row["avg_positive_return"] == pytest.approx(0.02)
    assert row["avg_negative_return_abs"] == pytest.approx(0.015)
    assert row["downside_upside_ratio"] == pytest.approx(0.75)
    last = bars[-1]
    bars[-1] = DailyBar(last.trade_date, last.open, last.high + 20, last.low - 20, last.close, last.volume)
    expanded = calculate_features(bars)
    assert expanded["atr_contraction_ratio"] == row["atr_contraction_ratio"]
    assert expanded["range_contraction_ratio"] == row["range_contraction_ratio"]
    assert expanded["atr_expansion_ratio"] > row["atr_expansion_ratio"]
    assert scored(signed_efficiency_ratio_10d=0)["alpha_score"] == scored(signed_efficiency_ratio_10d=1)["alpha_score"]

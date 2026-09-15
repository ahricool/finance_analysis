from __future__ import annotations

from datetime import date, timedelta

import pytest

from finance_analysis.trend_following.state import transition_state
from finance_analysis.trend_following.features import (  # pragma: allowlist secret
    absolute_trend_passes,
    calculate_atr,
    calculate_features,
    weighted_log_regression,
)
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.ranking import rank_candidates
from finance_analysis.trend_following.regime import (
    calculate_market_regime,
    realized_volatility_20d,
)  # pragma: allowlist secret
from finance_analysis.trend_following.scoring import (  # pragma: allowlist secret
    calculate_rs_score,
    calculate_trend_score,
)

TRADE_DATE = date(2026, 8, 28)


def bars(*, count: int = 80, start: float = 100.0, step: float = 1.0, final: float | None = None):
    result = []
    for index in range(count):
        close = start + index * step
        if final is not None and index == count - 1:
            close = final
        result.append(
            DailyBar(
                TRADE_DATE - timedelta(days=count - index - 1),
                close - 0.5,
                close + 1.0,
                close - 1.0,
                close,
                1_000 + index * 10,
            )
        )
    return result


def test_weighted_slope_r_squared_returns_drawdown_and_atr():
    series = bars(step=1.0)
    slope, r_squared = weighted_log_regression([item.close for item in series])
    features = calculate_features(series)
    assert slope > 0
    assert r_squared > 0.99
    assert features is not None
    assert features["return_5d"] == pytest.approx(series[-1].close / series[-6].close - 1)
    assert features["return_10d"] == pytest.approx(series[-1].close / series[-11].close - 1)
    assert features["return_20d"] == pytest.approx(series[-1].close / series[-21].close - 1)
    assert features["drawdown_20d"] == 0
    assert "return_60d" not in features
    assert "drawdown_60d" not in features
    assert "ma60" not in features
    assert calculate_atr(series) == pytest.approx(2.0)


def test_breakouts_exclude_the_current_bar():
    series = bars(start=100, step=0, final=101)
    result = calculate_features(series)
    assert result is not None
    assert result["previous_high_20"] == 101  # previous close 100 plus the raw high offset
    assert result["breakout_10d"] is False
    assert result["breakout_20d"] is False
    series[-1] = DailyBar(series[-1].trade_date, 101, 103, 100, 102, 3_000)
    result = calculate_features(series)
    assert result is not None
    assert result["breakout_10d"] is True
    assert result["breakout_20d"] is True
    assert "breakout_55d" not in result


def test_cross_section_scores_and_rs_vs_market():
    first = calculate_features(bars(step=1.2))
    second = calculate_features(bars(step=0.4))
    assert first and second
    rows = []
    for code, item in (("AAA.US", first), ("BBB.US", second)):
        item.update(
            code=code,
            rs_5d=item["return_5d"] - 0.005,
            rs_10d=item["return_10d"] - 0.01,
            rs_20d=item["return_20d"] - 0.02,
        )
        item["valid_setup"] = True
        rows.append(item)
    ranked = rank_candidates(rows)
    assert ranked[0]["weighted_slope_percentile"] == 100
    assert ranked[0]["return_20d_percentile"] == 100
    for row in ranked:
        assert 0 <= row["trend_score"] <= 100
        assert 0 <= row["rs_score"] <= 100
        assert 0 <= row["breakout_score"] <= 100
        assert 0 <= row["alpha_score"] <= 100


def test_short_horizon_score_weights_and_absolute_trend_three_of_four():
    trend, trend_components = calculate_trend_score(
        {
            "weighted_slope_percentile": 80.0,
            "weighted_r2": 0.9,
            "return_10d": 0.04,
            "return_20d": 0.08,
            "drawdown_20d": -0.04,
        }
    )
    assert trend == pytest.approx(77.0)
    assert set(trend_components) == {
        "weighted_slope_percentile",
        "weighted_r2",
        "return_10d",
        "return_20d",
        "drawdown_quality",
    }
    rs, rs_components = calculate_rs_score(
        {
            "rs_5d": 0.02,
            "rs_10d": 0.03,
            "rs_20d": 0.04,
            "return_10d_percentile": 70.0,
            "return_20d_percentile": 80.0,
        }
    )
    assert rs == pytest.approx(63.075)
    assert set(rs_components) == {"rs_5d", "rs_10d", "rs_20d", "percentile_10d", "percentile_20d"}
    assert absolute_trend_passes([True, True, True, False]) is True
    assert absolute_trend_passes([True, True, False, False]) is False


def test_short_breakout_and_trend_resume_setups():
    breakout_10 = calculate_features(bars(start=100, step=0))
    assert breakout_10 is not None
    breakout_10.update(
        code="BREAKOUT.US",
        rs_5d=0.01,
        rs_10d=0.02,
        rs_20d=0.03,
    )
    breakout_10["breakout_10d"] = True
    breakout_10["breakout_20d"] = False
    breakout_10["compression_breakout"] = False
    breakout_10["setup"] = "BREAKOUT_10D"
    breakout_10["valid_setup"] = True

    resumed = calculate_features(bars(step=0.5))
    assert resumed is not None
    resumed.update(
        code="RESUME.US",
        rs_5d=0.01,
        rs_10d=0.02,
        rs_20d=0.03,
        breakout_10d=False,
        breakout_20d=False,
        compression_breakout=False,
        valid_setup=False,
        setup="NONE",
        trend_resume_base=True,
    )
    ranked = rank_candidates([breakout_10, resumed])
    by_code = {row["code"]: row for row in ranked}
    assert by_code["BREAKOUT.US"]["setup"] == "BREAKOUT_10D"
    assert by_code["RESUME.US"]["setup"] == "TREND_RESUME"
    assert by_code["RESUME.US"]["valid_setup"] is True
    assert all(row["setup"] != "BREAKOUT_55D" for row in ranked)


def test_market_regime_uses_raw_bars_and_own_breadth_universe():
    benchmark = bars(step=1.0)
    result = calculate_market_regime(
        benchmark,
        {"AAA.US": bars(step=1.0), "BBB.US": bars(step=-0.2, start=130)},
        market="US",
        trade_date=TRADE_DATE,
        benchmark_code="SPY.US",
    )
    assert result["market_regime"] in {"RISK_ON", "NEUTRAL", "RISK_OFF"}
    assert result["features"]["breadth_ready_count"] == 2
    assert result["features"]["above_ma10_ratio"] == pytest.approx(0.5)
    assert result["features"]["above_ma20_ratio"] == pytest.approx(0.5)
    assert "above_ma60_ratio" not in result["features"]
    assert "max_drawdown_60d" not in result["features"]
    assert 0 <= result["market_score"] <= 100


def _row(**updates):
    row = {
        "code": "AAA.US",
        "open": 109.0,
        "reference_price": 110.0,
        "atr20": 2.0,
        "recent_structure_low": 104.0,
        "previous_low_10": 100.0,
        "ma10": 108.0,
        "ma20": 104.0,
        "ma20_slope": 0.01,
        "trend_score": 80.0,
        "rs_score": 80.0,
        "alpha_score": 80.0,
        "is_candidate": True,
        "trend_candidate": True,
    }
    row.update(updates)
    return row


def test_candidate_trend_state():
    candidate = transition_state(_row(), None)
    assert candidate.state == "CANDIDATE"
    assert set(candidate.to_dict()) == {"state", "reasons"}
    assert transition_state(_row(is_candidate=False), None).state == "WATCHING"
    assert transition_state(_row(is_candidate=False, trend_candidate=False), None).state == "IDLE"


def test_candidate_becomes_healthy_trend():
    previous = {"state": "CANDIDATE"}
    assert transition_state(_row(), previous).state == "TRENDING"
    assert transition_state(_row(is_candidate=False), previous).state == "TRENDING"


def test_weakening_broken_and_recovery_transitions():
    previous = {"state": "TRENDING"}
    weak = transition_state(_row(rs_score=50), previous)
    assert weak.state == "WEAKENING"
    broken = transition_state(_row(reference_price=99), previous)
    assert broken.state == "BROKEN"
    assert transition_state(_row(reference_price=99), broken.to_dict()).state == "BROKEN"
    assert transition_state(_row(), weak.to_dict()).state == "TRENDING"
    assert transition_state(_row(), broken.to_dict()).state == "CANDIDATE"
    assert transition_state(_row(reference_price=103, previous_low_10=90, ma20_slope=-0.01), previous).state == "BROKEN"


def test_realized_volatility_uses_exactly_20_returns():
    closes = [100.0 + index for index in range(30)]
    recent = closes[-21:]
    expected = recent[1:]
    assert len(recent) == 21
    assert len([right / left - 1 for left, right in zip(recent, expected)]) == 20
    value = realized_volatility_20d(closes)
    import numpy as np

    daily = np.asarray(recent[1:]) / np.asarray(recent[:-1]) - 1.0
    assert len(daily) == 20
    assert value == pytest.approx(float(np.std(daily, ddof=1) * (252**0.5)))

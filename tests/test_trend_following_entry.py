"""Entry research regressions using actual historical features and isolated score fixtures."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.entry import calculate_entry
from finance_analysis.trend_following.features import calculate_features
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.ranking import rank_candidates
from finance_analysis.trend_following.scoring import calculate_trend_score
from finance_analysis.trend_following.state import transition_state


def bars(closes):
    return [DailyBar(date(2026, 1, 1) + timedelta(days=i), c, c + .5, c - .5, c, 1000)
            for i, c in enumerate(closes)]


def resume_bars():
    return bars([100 + i for i in range(50)] + [147, 144.5, 147])


def ranked(series, **kwargs):
    row = calculate_features(series, **kwargs)
    row.update(code="AAA.US", rs_5d=.08, rs_10d=.12, rs_20d=.18)
    return rank_candidates([row])[0]


def entry_row(**updates):
    row = ranked(resume_bars())
    row.update(trend_score=85, rs_score=80, alpha_score=85, path_score=90,
               ma20_slope=.01, distance_from_ma20=.05, fragility_score=None,
               breakout_20d=True, close_location_value=.9)
    row["score_breakdown"]["setup"].update(breakout_quality=99, volume_quality=90)
    row.update(updates)
    return row


def test_r2_direction_is_continuous_and_keeps_raw_values():
    row = ranked(bars([100 + i for i in range(50)]))
    def quality(slope):
        _, breakdown = calculate_trend_score({**row, "raw_weighted_slope": slope, "weighted_r2": .99})
        assert breakdown["raw_weighted_r2"] == .99
        assert breakdown["raw_weighted_slope"] == slope
        return breakdown["weighted_r2"]
    assert quality(.01) > 98
    assert quality(-.01) < 1
    assert quality(-1e-8) < quality(0) < quality(1e-8)
    assert quality(1e-8) - quality(-1e-8) < .001


def test_actual_pullback_reclaims_ma10_and_produces_resume_entry():
    row = ranked(resume_bars())
    assert row["pullback_detected"] and row["ma10_reclaimed"] and row["pullback_structure_intact"]
    assert row["trend_resume"] and row["setup"] == "PULLBACK_RESUME"
    result = calculate_entry(row)
    assert result["entry_type"] == "PULLBACK_RESUME"
    assert result["entry_score"] > 75


def test_continuing_trend_is_not_resume_and_broken_pullback_is_rejected():
    row = ranked(bars([100 + i for i in range(53)]))
    assert not row["trend_resume"]
    broken = ranked(bars([100 + i for i in range(50)] + [130, 142, 148.5]))
    assert broken["pullback_detected"] and broken["ma10_reclaimed"]
    assert not broken["pullback_structure_intact"] and not broken["trend_resume"]
    assert calculate_entry(broken)["entry_type"] == "NONE"


def test_insufficient_pullback_history_is_not_assumed_intact():
    row = ranked(resume_bars()[-21:])
    assert not row["pullback_structure_intact"] and not row["trend_resume"]


@pytest.mark.parametrize("location,expected", [("high", 1), ("low", 0), ("flat", None)])
def test_clv_and_atr_percent(location, expected):
    series = resume_bars()
    last = series[-1]
    series[-1] = replace(last, high=last.close if location != "low" else last.close + 1,
                         low=last.close if location != "high" else last.close - 1)
    row = calculate_features(series)
    assert row["close_location_value"] == expected
    assert row["atr_percent"] == pytest.approx(row["atr20"] / last.close)
    assert "trend_quality" not in row


def test_cumulative_downside_accounts_for_number_of_days():
    def ratio(returns):
        closes = [100.] * 30
        for r in returns:
            closes.append(closes[-1] * (1 + r))
        return calculate_features(bars(closes))["downside_upside_ratio"]
    assert ratio([.01] * 8 + [-.01] * 2) == pytest.approx(.25)
    assert ratio([.04] + [-.01] * 9) == pytest.approx(2.25)


def test_breakout_gates_priority_and_missing_fragility():
    row = entry_row(trend_resume=True)
    good = calculate_entry(row)
    assert good["entry_type"] == "BREAKOUT" and good["entry_score"] > 85
    assert "fragility" not in good["entry_breakdown"]["breakout"]["normalized_weights"]
    for updates in [dict(distance_from_ma20=.25), dict(close_location_value=.1),
                    dict(close_location_value=None), dict(fragility_score=50),
                    dict(breakout_20d=False, breakout_10d=False, compression_breakout=False, trend_resume=False)]:
        result = calculate_entry({**row, **updates})
        assert result["entry_type"] == "NONE" and result["entry_score"] == 0
    actual = ranked(resume_bars()[:-1] + [replace(resume_bars()[-1], close=152, high=153)])
    assert actual["breakout_20d"] and not actual["trend_resume"]
    assert actual["setup"] == "BREAKOUT_20D"


def test_preview_volume_is_provisional_not_a_low_volume_veto():
    series = resume_bars()
    series[-1] = replace(series[-1], volume=1)
    official = ranked(series)
    preview = ranked(series, preview=True)
    for key in official:
        if key not in {"volume_provisional", "breakout_score", "setup_score", "alpha_score", "score_breakdown", "is_candidate"}:
            assert official[key] == preview[key]
    assert preview["raw_volume_ratio"] == .001 and preview["projected_volume_ratio"] is None
    assert preview["score_breakdown"]["setup"]["volume_quality"] == 50
    # Only the volume component may change Alpha.
    expected = .15 * .15 * (50 - official["score_breakdown"]["setup"]["volume_quality"])
    assert preview["alpha_score"] - official["alpha_score"] == pytest.approx(expected, abs=.0001)
    row = entry_row(volume_provisional=True, raw_volume_ratio=.001, projected_volume_ratio=None)
    result = calculate_entry(row)
    assert result["entry_type"] == "BREAKOUT" and result["entry_score"] > 85
    assert "volume" not in result["entry_breakdown"]["breakout"]["normalized_weights"]


def test_entry_does_not_mutate_alpha_rank_candidate_or_state():
    row = entry_row()
    before = deepcopy(row)
    decision = transition_state(row, None)
    result = calculate_entry(row)
    assert row == before
    row.update(result)
    assert transition_state(row, None) == decision
    assert calculate_entry(before, replace(DEFAULT_CONFIG, entry_alpha_min=101))["entry_score"] == 0
    assert all(row[key] == before[key] for key in ("alpha_score", "rank", "is_candidate"))


def test_actual_twenty_day_breakout_has_high_entry_quality():
    series = bars([100 + .5 * i for i in range(50)] + [126])
    series[-1] = replace(series[-1], high=126, low=124.5)
    row = ranked(series)
    assert row["breakout_20d"] and not row["trend_resume"]
    result = calculate_entry(row)
    assert result["entry_type"] == "BREAKOUT"
    assert result["entry_score"] > 80
    assert result["entry_breakdown"]["breakout"]["components"]["breakout"] > 90

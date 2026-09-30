"""Point-in-time structure fixtures; no market/network dependencies."""

from dataclasses import replace
from datetime import date, timedelta
import json
import math

import pytest

from finance_analysis.trend_following.box import BoxCandidate, select_box
from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.features import calculate_features
from finance_analysis.trend_following.models import DailyBar


def box_bars(days=60, close=103.0):
    bars = []
    for i in range(days):
        price = 100 + 2 * math.sin(2 * math.pi * i / 5)
        bars.append(DailyBar(date(2026, 1, 1) + timedelta(days=i), price, price + 2, price - 2, price, 1000, None))
    bars.append(
        DailyBar(date(2026, 1, 1) + timedelta(days=days), 102, close + 0.1, min(101, close - 1), close, 1000, None)
    )
    return bars


def calculate(bars, **kwargs):
    result = calculate_features(bars, **kwargs)
    assert result is not None
    json.dumps(result, allow_nan=False)
    return result


def test_sideways_and_longest_near_tie():
    result = calculate(box_bars())
    assert result["box_quality"] >= 70
    assert result["box_state"] == "BOX_READY"
    assert result["box_window_days"] == 60
    assert result["box_start_date"] == "2026-01-01"
    assert result["box_end_date"] == "2026-03-01"
    assert result["box_upper_touches"] >= 2


@pytest.mark.parametrize("direction", [-1, 1])
def test_directional_channels_are_not_high_quality_boxes(direction):
    bars = box_bars()
    for i, bar in enumerate(bars):
        price = 100 + direction * i * 0.35
        bars[i] = replace(bar, open=price, high=price + 0.3, low=price - 0.3, close=price)
    result = calculate(bars)
    assert result["box_state"] == "NONE"
    assert result["box_quality"] is None or result["box_quality"] < 70


def test_wide_and_dead_ranges_rejected():
    for width in (20, 0):
        bars = [replace(b, high=100 + width, low=100 - width, open=100, close=100) for b in box_bars()]
        assert calculate(bars)["box_state"] == "NONE"


@pytest.mark.parametrize("days", [20, 30, 40])
def test_selects_established_box_after_wider_history(days):
    bars = box_bars()
    for i in range(len(bars) - days - 1):
        bars[i] = replace(bars[i], high=120, low=80)
    assert calculate(bars)["box_window_days"] == days


def test_tie_band_is_global_not_transitive():
    candidates = [BoxCandidate(15, 90, {}), BoxCandidate(30, 88, {}), BoxCandidate(60, 86, {})]
    assert select_box(candidates, 3).days == 30
    assert select_box(candidates, 0).days == 15


@pytest.mark.parametrize("preview", [False, True])
def test_today_cannot_change_box_geometry_quality_or_historical_atr(preview):
    bars = box_bars()
    before = calculate(bars, preview=preview)
    bars[-1] = replace(bars[-1], high=200, low=50, close=110)
    after = calculate(bars, preview=preview)
    dynamic = {"box_state", "box_breakout_distance_atr"}
    for key in before:
        if key.startswith("box_") and key not in dynamic:
            assert before[key] == after[key], key


@pytest.mark.parametrize(
    "distance_atr,clv,expected",
    [
        (0.25, 0.9, "BOX_BREAKOUT"),
        (0.05, 0.9, "BOX_READY"),
        (2.01, 0.9, "NONE"),
        (0.25, 0.5, "NONE"),
        (0.25, None, "NONE"),
    ],
)
def test_breakout_thresholds(distance_atr, clv, expected):
    bars = box_bars()
    initial = calculate(bars)
    close = initial["box_high"] + distance_atr * initial["box_atr20"]
    low = close - (clv or 0) * 2
    high = low + 2 if clv is not None else close
    bars[-1] = replace(bars[-1], close=close, high=high, low=low)
    assert calculate(bars)["box_state"] == expected


def test_ready_one_percent_and_forming_far_from_top_and_broken_bottom():
    bars = box_bars()
    initial = calculate(bars)
    for close, expected in [
        (initial["box_high"] * 0.99, "BOX_READY"),
        (initial["box_high"] * 0.96, "BOX_FORMING"),
        (initial["box_low"] - 0.1, "NONE"),
    ]:
        bars[-1] = replace(bars[-1], close=close, high=close + 0.2, low=close - 1)
        assert calculate(bars)["box_state"] == expected


def test_history_is_sufficient_and_future_append_does_not_change_replay():
    bars = box_bars()
    assert calculate(bars[:21])["box_window_days"] <= 20
    original = calculate(bars)
    replay = bars + [replace(bars[-1], trade_date=bars[-1].trade_date + timedelta(days=1), close=150, high=160)]
    assert calculate([b for b in replay if b.trade_date <= bars[-1].trade_date]) == original
    # Extending service history by one bar for 60-day boxes changes no old feature.
    old = calculate(bars[-60:])
    assert {k: v for k, v in original.items() if not k.startswith(("box_", "distance_to_box"))} == {
        k: v for k, v in old.items() if not k.startswith(("box_", "distance_to_box"))
    }


def test_configuration_can_disable_windows_without_changing_existing_features():
    bars = box_bars()
    enabled = calculate(bars)
    disabled = calculate(bars, config=replace(DEFAULT_CONFIG, box_windows=(100,)))
    assert {k: v for k, v in enabled.items() if not k.startswith(("box_", "distance_to_box"))} == {
        k: v for k, v in disabled.items() if not k.startswith(("box_", "distance_to_box"))
    }


def test_box_is_inert_for_cross_section_scores_candidate_entry_and_state():
    from copy import deepcopy
    from finance_analysis.trend_following.entry import calculate_entry
    from finance_analysis.trend_following.ranking import rank_candidates
    from finance_analysis.trend_following.state import transition_state

    rows = []
    for i, close in enumerate((103, 105, 110)):
        row = calculate(box_bars(close=close))
        row.update(code=f"BOX{i}.US", rs_5d=0.05, rs_10d=0.08, rs_20d=0.1)
        rows.append(row)
    baseline = [{k: v for k, v in row.items() if not k.startswith(("box_", "distance_to_box"))} for row in rows]
    enabled, disabled = rank_candidates(deepcopy(rows)), rank_candidates(baseline)
    keys = ("alpha_score", "trend_score", "rs_score", "setup_score", "path_score", "rank", "is_candidate")
    for actual, expected in zip(enabled, disabled):
        assert {k: actual[k] for k in keys} == {k: expected[k] for k in keys}
        assert calculate_entry(actual) == calculate_entry(expected)
        assert transition_state(actual, None) == transition_state(expected, None)


def test_service_preview_uses_official_history_and_replaces_today_without_lookahead(monkeypatch):
    from dataclasses import asdict
    from types import SimpleNamespace
    from finance_analysis.trend_following.models import UniverseMember
    from finance_analysis.trend_following.service import TrendFollowingService

    bars = box_bars()
    today = bars[-1].trade_date
    future = replace(bars[-1], trade_date=today + timedelta(days=1), high=999, close=999)
    histories = bars + [future]
    repository = SimpleNamespace(
        market="US",
        daily_codes_on_date=lambda codes, day: codes,
        load_daily_history=lambda *a, **kw: [dict(asdict(bar), code="BOX.US") for bar in histories],
        previous_snapshots=lambda *a: {},
        health_history=lambda *a: {},
    )
    market_data = SimpleNamespace(get_daily_bars=lambda *a, **kw: SimpleNamespace(data={"SPY.US": histories}))
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe", lambda market: (UniverseMember("US", "BOX.US", "Box"),)
    )
    service = TrendFollowingService("US", repository, market_data=market_data)
    official = service._run_single_date(today, persist=False)["snapshots"][0]["features"]
    assert official["box_window_days"] == 60
    assert official["box_state"] == "BOX_READY"
    close = official["box_high"] + 0.25 * official["box_atr20"]
    current = replace(bars[-1], close=close, high=close + 0.1, low=close - 2)
    preview = service._run_single_date(today, persist=False, overlay_bars={"BOX.US": current, "SPY.US": current})
    feature = preview["snapshots"][0]["features"]
    assert feature["box_state"] == "BOX_BREAKOUT"
    assert feature["volume_provisional"] is True
    for key in ("box_high", "box_low", "box_quality", "box_atr20", "box_window_days", "box_end_date"):
        assert feature[key] == official[key]
    histories[-2] = replace(histories[-2], high=888, low=1, close=800)
    repeated = service._run_single_date(today, persist=False, overlay_bars={"BOX.US": current, "SPY.US": current})
    assert repeated["snapshots"][0]["features"] == feature


def test_fresh_breakout_only_once_during_three_day_continuation():
    bars = box_bars()
    for i in range(50, 60):
        close = 100 + math.sin(i * 2 * math.pi / 5)
        bars[i] = replace(bars[i], open=close, close=close, high=close + .5, low=close - .5)
    result = calculate(bars)
    assert result['box_quality'] >= 70
    assert result['atr_contraction_ratio'] < 1
    assert result['range_contraction_ratio'] < 1
    states = []
    for day in range(3):
        if day:
            bars.append(replace(bars[-1], trade_date=bars[-1].trade_date + timedelta(days=1)))
        previous = calculate(bars)
        close = previous['box_high'] + .3 * previous['box_atr20']
        bars[-1] = replace(bars[-1], close=close, open=close - .5, high=close + .05, low=close - 1)
        current = calculate(bars)
        assert current['box_quality'] >= 70
        states.append(current['box_state'])
        assert current['box_prior_breakout_confirmed'] is (day > 0)
        assert current['box_breakout_fresh'] is (day == 0)
    assert states == ['BOX_BREAKOUT', 'NONE', 'NONE']


@pytest.mark.parametrize('previous_kind', ['weak', 'wick', 'low_clv'])
def test_unconfirmed_yesterday_does_not_block_first_confirmation(previous_kind):
    bars = box_bars()
    base = calculate(bars)
    high, atr = base['box_high'], base['box_atr20']
    close = high + (.05 if previous_kind == 'weak' else .3) * atr
    if previous_kind == 'wick':
        close = high - .2
    yesterday = replace(bars[-1], close=close, open=close - .1, high=close + (.4 if previous_kind == 'low_clv' else .1), low=close - (.2 if previous_kind == 'low_clv' else 1))
    bars[-1] = yesterday
    bars.append(replace(yesterday, trade_date=yesterday.trade_date + timedelta(days=1)))
    geometry = calculate(bars)
    close = geometry['box_high'] + .3 * geometry['box_atr20']
    bars[-1] = replace(bars[-1], close=close, high=close + .1, low=close - 1)
    result = calculate(bars)
    assert result['box_state'] == 'BOX_BREAKOUT'
    assert result['box_prior_breakout_confirmed'] is False


@pytest.mark.parametrize('direction', [1, -1])
def test_flatness_rejects_directional_channel_independently_of_width(direction):
    bars = box_bars()
    for i, bar in enumerate(bars):
        close = 100 + direction * i * .1
        bars[i] = replace(bar, open=close, close=close, high=close + .15, low=close - .15)
    # Lower the admission threshold solely to inspect the rejected candidate's components.
    config = replace(DEFAULT_CONFIG, box_forming_quality_min=0)
    measured = calculate(bars, config=config)
    assert measured['box_width_pct'] < DEFAULT_CONFIG.box_max_width_pct
    assert measured['box_flatness_quality'] < 10
    assert measured['box_quality'] < DEFAULT_CONFIG.box_ready_quality_min
    assert calculate(bars)['box_state'] != 'BOX_READY'

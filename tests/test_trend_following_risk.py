"""Risk sizing units, boundaries, and unchanged arithmetic ATR contract."""

import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.features import calculate_atr
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.risk import calculate_risk_sizing


@pytest.mark.parametrize('low,distance,stop,position,basis', [
    (24, .04, 23.75, .20, 'ATR'),
    (23, .08, 23, .125, 'STRUCTURE'),
    (23.75, .05, 23.75, .20, 'ATR'),
])
def test_stop_and_position(low, distance, stop, position, basis):
    result = calculate_risk_sizing(25, .5, low)
    assert result['atr_stop_pct'] == pytest.approx(.05)
    assert result['structure_stop_pct'] == pytest.approx(distance)
    assert result['stop_loss_pct'] == pytest.approx(max(.05, distance))
    assert result['stop_price'] == pytest.approx(stop)
    assert result['suggested_position_pct'] == pytest.approx(position)
    assert result['stop_basis'] == basis
    assert result['risk_budget_pct'] == .01
    json.dumps(result, allow_nan=False)


def test_position_cap_and_custom_configuration():
    assert calculate_risk_sizing(25, .01, None)['suggested_position_pct'] == .25
    config = replace(DEFAULT_CONFIG, risk_budget_pct=.02, risk_stop_atr_multiple=3, risk_max_position_pct=.1)
    result = calculate_risk_sizing(25, .5, None, config)
    assert result['stop_loss_pct'] == pytest.approx(.06)
    assert result['suggested_position_pct'] == .1
    assert result['risk_budget_pct'] == .02
    assert result['atr_multiple'] == 3


@pytest.mark.parametrize('low', [None, 0, -1, 25, 26, float('nan'), float('inf')])
def test_missing_or_invalid_structure_uses_atr(low):
    result = calculate_risk_sizing(25, .5, low)
    assert result['structure_stop_pct'] == 0
    assert result['stop_basis'] == 'ATR'
    assert result['suggested_position_pct'] == pytest.approx(.2)


@pytest.mark.parametrize('invalid', [None, 0, -1, float('nan'), float('inf'), -float('inf')])
@pytest.mark.parametrize('field', ['price', 'atr'])
def test_invalid_required_input_returns_none(invalid, field):
    assert calculate_risk_sizing(invalid if field == 'price' else 25,
                                 invalid if field == 'atr' else .5, 24) is None


def test_extreme_arithmetic_returns_none():
    assert calculate_risk_sizing(1e-300, 1e300, None) is None
    assert calculate_risk_sizing(1e300, 1e-300, None) is None


@pytest.mark.parametrize('atr', [10, 20])
def test_stop_at_or_above_one_hundred_percent_returns_none(atr):
    assert calculate_risk_sizing(25, atr, None) is None


def test_stop_just_below_one_hundred_percent_remains_valid():
    result = calculate_risk_sizing(25, 9.9, None)
    assert result['stop_loss_pct'] == pytest.approx(.99)
    assert result['stop_price'] == pytest.approx(.25)
    json.dumps(result, allow_nan=False)


def test_atr_is_last_twenty_true_ranges_arithmetic_mean():
    # An old shock must leave the rolling window entirely, unlike Wilder smoothing.
    bars = [DailyBar(date(2026, 1, 1) + timedelta(days=i), 100, 101, 99, 100, 1) for i in range(30)]
    bars[2] = replace(bars[2], high=200)
    bars[-1] = replace(bars[-1], high=105)
    assert calculate_atr(bars) == pytest.approx((19 * 2 + 6) / 20)

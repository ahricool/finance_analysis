from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import math

import pytest

from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.structure import box, pivots
from finance_analysis.interfaces.api.v1.schemas.intraday_options import IntradayStructure
from tests.intraday_options.test_scoring import START, candles


def prices(values):
    bars = candles([0] * len(values))
    for i, value in enumerate(values):
        previous = values[max(0, i - 1)]
        bars[i] = replace(bars[i], open=Decimal(str(previous)), close=Decimal(str(value)),
                          high=Decimal(str(max(previous, value) + .05)), low=Decimal(str(min(previous, value) - .05)))
    return bars


def structure(bars, now=None):
    result = calculate('SPY.US', bars, now or bars[-1].bar_time + timedelta(minutes=1))
    return IntradayStructure.model_validate(result['structure']).model_dump(mode='json')


def oscillation(count=40):
    return [100 + math.sin(i * math.pi / 4) for i in range(count)]


def test_trends_are_symmetric_and_opening_warms_up():
    assert structure(candles([.0004] * 60))['kind'] == 'uptrend'
    assert structure(candles([-.0004] * 60))['kind'] == 'downtrend'
    assert structure(candles([.0004] * 20))['phase'] == 'warming'


def test_range_requires_actual_box_before_breakout():
    bars = prices(oscillation())
    assert structure(bars)['kind'] == 'range'
    assert box(bars, bars[-1].bar_time) is not None
    assert structure(prices(list(range(100, 140))))['kind'] == 'uptrend'


def test_box_breakout_freezes_bounds_confirms_then_fails():
    base = oscillation()
    first = structure(prices(base + [102]))
    confirmed = structure(prices(base + [102, 102.2]))
    assert first['kind'] == 'breakout_up' and first['phase'] == 'forming'
    assert confirmed['kind'] == 'breakout_up' and confirmed['phase'] == 'confirmed'
    assert first['box'] == confirmed['box']
    assert confirmed['box']['upper'] < 102
    failed = structure(prices(base + [102, 102.2, 100, 100]))
    assert failed['kind'] == 'failed_up'
    assert failed['phase'] == 'failed'
    lower = structure(prices(base + [98, 97.8]))
    assert lower['kind'] == 'breakout_down' and lower['phase'] == 'confirmed'


def test_gap_cannot_confirm_breakout_and_is_marked():
    full = prices(oscillation() + [102, 102.1, 102.2])
    missing = full[:41] + full[42:]
    result = structure(missing)
    assert result['kind'] == 'breakout_up' and result['phase'] == 'forming'
    assert result['reference'] and result['missing_bars'] == 1


def test_pivot_confirmation_needs_two_real_right_hand_minutes():
    bars = candles([0] * 5)
    bars[2] = replace(bars[2], high=Decimal("103"))
    assert pivots(bars[:4]) == []
    points = pivots(bars)
    assert points and all(p['confirmed_at'] <= (bars[-1].bar_time + timedelta(minutes=1)).isoformat() for p in points)
    assert not pivots(bars[:3] + bars[4:])


def test_future_and_unclosed_candles_cannot_change_structure():
    bars = prices(oscillation() + [102, 102.2])
    now = bars[-1].bar_time + timedelta(minutes=1)
    expected = structure(bars, now)
    future = replace(bars[-1], bar_time=now, close=Decimal('200'), high=Decimal('201'), confirmed=False)
    assert structure(bars + [future], now) == expected
    assert structure(bars + [replace(future, confirmed=True)], now) == expected


@pytest.mark.parametrize('field,value', [('partial', True), ('sampled', True), ('close', Decimal('0'))])
def test_invalid_minutes_are_reference_only(field, value):
    bars = candles([.0004] * 60)
    bars[-10] = replace(bars[-10], **{field: value})
    result = structure(bars)
    assert result['reference'] and result['missing_bars'] == 1
    assert result['kind'] == 'uptrend'


def test_retest_and_new_breakout_after_failure():
    result = structure(prices(oscillation() + [102, 102.2, 101.1, 101.3]))
    assert result['kind'] == 'breakout_up' and result['phase'] == 'retest'
    again = structure(prices(oscillation() + [102, 102.2, 100, 100, 102, 102.3]))
    assert again['kind'] == 'breakout_up' and again['phase'] == 'confirmed'


def test_rebound_keeps_bearish_background_and_pullback_is_symmetric():
    base = [110 - .12 * i + .25 * math.sin(i * math.pi / 3) for i in range(55)]
    values = base + [base[-1] + .3 * (j + 1) for j in range(5)]
    result = structure(prices(values))
    assert result['kind'] == 'rebound' and result['background'] == 'bearish'
    assert result['oversold']
    inverse = structure(prices([220 - v for v in values]))
    assert inverse['kind'] == 'pullback' and inverse['background'] == 'bullish'


def test_gap_at_latest_confirmation_prevents_ordinary_confirmation():
    bars = candles([.0004] * 60)
    result = structure(bars[:-2] + bars[-1:])
    assert result['phase'] == 'forming'
    assert result['reference']


def test_tiny_motion_is_not_a_directional_trend():
    result = structure(candles([.0000001] * 60))
    assert result['kind'] == 'unclear'
    assert result['background'] == 'neutral'


def test_direct_opposite_break_cannot_remain_confirmed_up():
    result = structure(prices(oscillation() + [102, 102.2, 98, 97.8]))
    assert result['kind'] == 'failed_up' and result['phase'] == 'failed'

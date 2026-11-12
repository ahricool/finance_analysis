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


@pytest.mark.parametrize('side', [1, -1])
def test_mild_breakout_keeps_trigger_box_and_atr_while_continuing(side):
    values = [100 + side * (v - 100) for v in oscillation() + [101.18, 101.18, 101.48]]
    first = structure(prices(values[:-2]))
    confirmed = structure(prices(values[:-1]))
    continued = structure(prices(values))
    assert first['phase'] == 'forming'
    assert confirmed['phase'] == 'confirmed'
    assert continued['phase'] in {'confirmed', 'retest'}
    assert continued['kind'] == ('breakout_up' if side > 0 else 'breakout_down')
    assert first['box'] == confirmed['box'] == continued['box']
    assert confirmed['confirmed_at'] == continued['confirmed_at']


def test_retest_stage_time_preserves_confirmation_and_does_not_drift():
    values = oscillation() + [102, 102.2, 101.1, 101.3]
    confirmed = structure(prices(values[:42]))
    retest = structure(prices(values))
    later = structure(prices(values + [101.4]))
    assert retest['phase'] == later['phase'] == 'retest'
    assert retest['confirmed_at'] == confirmed['since'] == confirmed['confirmed_at']
    assert retest['since'] == (START + timedelta(minutes=44)).isoformat().replace('+00:00', 'Z')
    assert retest['since'] != retest['confirmed_at']
    assert later['since'] == retest['since']
    assert later['confirmed_at'] == retest['confirmed_at']


def test_failure_time_stays_fixed_and_rebreak_has_new_confirmation():
    values = oscillation() + [102, 102.2, 100, 100]
    failed = structure(prices(values))
    waiting = structure(prices(values + [100]))
    again = structure(prices(values + [102, 102.3]))
    assert failed['phase'] == waiting['phase'] == 'failed'
    assert failed['since'] == waiting['since']
    assert failed['confirmed_at'] == waiting['confirmed_at']
    assert again['phase'] == 'confirmed'
    assert again['confirmed_at'] > failed['confirmed_at']
    assert again['box'] == failed['box']


def test_event_expires_fifteen_minutes_after_trigger_not_confirmation():
    values = oscillation() + [102 + .3 * i for i in range(16)]
    active = structure(prices(values[:-1]))
    expired = structure(prices(values))
    assert active['kind'] == 'breakout_up'
    assert active['confirmed_at'] is not None
    assert expired['kind'] != 'breakout_up'
    assert expired['confirmed_at'] is None


def test_missing_minute_does_not_confirm_failure_or_retest():
    full = prices(oscillation() + [102, 102.2, 100, 100])
    result = structure(full[:42] + full[43:])
    assert result['phase'] == 'confirmed'
    retest = prices(oscillation() + [102, 102.2, 101.1, 101.3])
    assert structure(retest[:42] + retest[43:])['phase'] == 'confirmed'


@pytest.mark.parametrize('side', [1, -1])
def test_unconfirmed_attempt_can_switch_side_but_needs_adjacent_confirmation(side):
    values = [100 + side * (v - 100) for v in oscillation() + [102, 98, 97.8]]
    first = structure(prices(values[:-1]))
    confirmed = structure(prices(values))
    assert first['phase'] == 'forming' and first['confirmed_at'] is None
    assert confirmed['phase'] == 'confirmed'
    assert confirmed['kind'] == ('breakout_down' if side > 0 else 'breakout_up')
    assert first['box'] == confirmed['box']

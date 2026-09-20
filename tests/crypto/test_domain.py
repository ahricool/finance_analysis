from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from finance_analysis.crypto.features import atr, breakout, ema
from finance_analysis.crypto.models import StrategyState
from finance_analysis.crypto.regime import market_regime
from finance_analysis.crypto.risk import initial_stop, trailing_stop
from finance_analysis.crypto.strategy import evaluate

from .helpers import START, candle


def test_ema_seed_and_regime_strict_comparisons():
    assert ema([D(1), D(2), D(3), D(4)], 3) == D(3)
    assert market_regime(D(110), D(105), D(100)) == "BULL"
    assert market_regime(D(90), D(95), D(100)) == "BEAR"
    assert market_regime(D(110), D(100), D(100)) == "RANGE"
    assert market_regime(D(90), D(105), D(100)) == "RANGE"


def test_breakout_excludes_current_high_and_requires_volume_above_median():
    bars = [candle(i) for i in range(21)]
    level = max(row.high for row in bars[:-1])
    bars[-1] = replace(bars[-1], high=level + 100, close=level + 1, volume=bars[-2].volume * 2)
    setup, actual, ratio = breakout(bars)
    assert (setup, actual, ratio) == ("BREAKOUT", level, D(2))
    bars[-1] = replace(bars[-1], volume=bars[-2].volume)
    assert breakout(bars)[0] == "NONE"
    bars[-1] = replace(bars[-1], close=level, volume=bars[-2].volume * 2)
    assert breakout(bars)[0] == "NONE"


def test_wilder_atr_and_stops_never_retreat():
    bars = [candle(i, open=D(100), high=D(102), low=D(98), close=D(100)) for i in range(16)]
    assert atr(bars) == 4
    assert initial_stop(D(100), D(4)) == 92
    stop = trailing_stop(D(120), D(4), D(92))
    assert stop == 110
    assert trailing_stop(D(121), D(20), stop) == stop


def warm_rows():
    rows = [candle(i) for i in range(240)]
    rows[-1] = replace(rows[-1], close=D(150), high=D(151), volume=D(100))
    return rows


def test_flat_long_flat_and_determinism_only_at_closed_quarter():
    rows = warm_rows()
    hourly = [candle(i, interval="1h") for i in range(60)]
    at = rows[-1].close_time
    assert evaluate(rows, hourly, at - timedelta(seconds=1), StrategyState()) is None
    assert evaluate([*rows[:-1], replace(rows[-1], closed=False)], hourly, at, StrategyState()) is None
    state, snapshot = evaluate(rows, hourly, at, StrategyState())
    assert (snapshot["regime"], snapshot["setup"], snapshot["action"], state.position_state) == (
        "BULL",
        "BREAKOUT",
        "BUY",
        "LONG",
    )
    assert state.highest_price_since_entry == state.entry_price == D(150)
    assert evaluate(rows, hourly, at, StrategyState()) == (state, snapshot)
    next_rows = [candle(i, open=D(151), high=D(152), low=D(149), close=D(151)) for i in range(240, 241)]
    held, hold = evaluate(rows + next_rows, hourly, next_rows[-1].close_time, state)
    assert held.position_state == "LONG" and hold["action"] == "HOLD"
    assert held.trailing_stop >= state.trailing_stop
    exit_rows = [candle(i, open=D(100), high=D(101), low=D(99), close=D(100)) for i in range(241, 242)]
    flat, exit_signal = evaluate(rows + next_rows + exit_rows, hourly, exit_rows[-1].close_time, held)
    assert exit_signal["action"] == "EXIT" and flat.position_state == "FLAT"
    assert flat.entry_price is None and exit_signal["initial_stop"] == held.initial_stop


def test_insufficient_history_records_wait_without_fake_regime():
    rows = [candle(i) for i in range(1)]
    state, signal = evaluate(rows, [], rows[-1].close_time, StrategyState())
    assert signal["regime"] == "UNKNOWN" and signal["action"] == "WAIT"
    assert state.position_state == "FLAT"


def test_invalid_candle_rejected():
    with pytest.raises(ValueError):
        candle(open_time=START.replace(tzinfo=None))
    with pytest.raises(ValueError):
        candle(close=D("NaN"))
    with pytest.raises(ValueError):
        candle(high=D(10))


def test_existing_stop_still_exits_after_indicator_history_gap():
    rows = [candle(i, open=D(90), high=D(91), low=D(89), close=D(90)) for i in range(1)]
    state = StrategyState(
        position_state="LONG",
        entry_price=D(100),
        entry_time=START,
        highest_price_since_entry=D(110),
        initial_stop=D(92),
        trailing_stop=D(95),
    )
    flat, snapshot = evaluate(rows, [], rows[-1].close_time, state)
    assert snapshot["action"] == "EXIT" and snapshot["regime"] == "UNKNOWN"
    assert flat.position_state == "FLAT"


def test_actions_indicators_and_stops_match_pre_position_revision():
    """Golden results captured from d8732c8, before the position model extension."""
    import json
    from pathlib import Path

    expected = json.loads((Path(__file__).parent / "fixtures/strategy_before_positions.json").read_text())
    q, h = warm_rows(), [candle(i, interval="1h") for i in range(60)]
    first = [candle()]
    _, wait = evaluate(first, [], first[-1].close_time, StrategyState())
    state, buy = evaluate(q, h, q[-1].close_time, StrategyState())
    assert (buy["position_before"], buy["position_after"], buy["position_delta"], buy["average_entry_price"]) == (
        0,
        1,
        1,
        D(150),
    )
    q += [candle(240, open=D(151), high=D(152), low=D(149), close=D(151))]
    state, hold = evaluate(q, h, q[-1].close_time, state)
    q += [candle(241, open=D(100), high=D(101), low=D(99), close=D(100))]
    state, exit = evaluate(q, h, q[-1].close_time, state)
    for actual, baseline in zip([wait, buy, hold, exit], expected):
        old_fields = {key: actual[key] for key in baseline}
        assert json.loads(json.dumps(old_fields, default=str)) == baseline
    assert (wait["position_before"], wait["position_after"], wait["position_delta"]) == (0, 0, 0)
    assert (hold["position_before"], hold["position_after"], hold["position_delta"]) == (1, 1, 0)
    assert (exit["position_before"], exit["position_after"], exit["position_delta"], exit["average_entry_price"]) == (
        1,
        0,
        -1,
        None,
    )

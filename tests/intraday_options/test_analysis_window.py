from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import math

import pytest

from finance_analysis.intraday_options.analysis_window import analysis_window, observed
from finance_analysis.intraday_options.runtime import data_status
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import transition
from finance_analysis.interfaces.api.v1.schemas.intraday_options import TrendResult
from tests.intraday_options.test_scoring import START, candles, score
from tests.intraday_options.test_structure import oscillation, prices
from tests.intraday_options.test_simulation import quote


@pytest.mark.parametrize("side", [1, -1])
def test_fourteen_is_warming_fifteen_can_judge_direction_with_longer_reference_windows(side):
    bars = candles([side * .0004] * 15)
    early, ready = score(bars[:-1]), score(bars)
    assert early["opportunities"]["reference"]
    assert early["structure"]["phase"] == "warming"
    assert not ready["opportunities"]["reference"]
    assert ready["structure"]["kind"] == ("uptrend" if side == 1 else "downtrend")
    assert ready["structure"]["recent_available_bars"] == 15
    assert ready["windows"][-1]["data_status"] == "warming"
    assert data_status(ready, START + timedelta(minutes=15), START.date(), "open") == "ready"


@pytest.mark.parametrize("side", [1, -1])
def test_fifteen_background_minutes_can_produce_confirmed_entry_after_two_real_trigger_closes(side):
    background = [100 + math.cos((i - 7) * math.pi / 3) for i in range(15)]
    values = [100 + side * (p - 100) for p in background + [101.3, 101.4]]
    forming, ready = score(prices(values[:-1])), score(prices(values))
    assert forming["opportunities"]["primary"] is None
    assert ready["opportunities"]["primary"]["kind"] == "box_breakout"
    assert ready["opportunities"]["primary"]["direction"] == ("bullish" if side == 1 else "bearish")


def test_old_invalid_history_is_reference_only_recent_invalid_minute_still_blocks():
    bars = prices(oscillation() + [101.3, 101.4])
    old = [replace(b, partial=True) if i == 5 else b for i, b in enumerate(bars)]
    result = score(old)
    assert result["opportunities"]["primary"]
    assert result["opportunities"]["missing_bars"] == 1
    assert result["opportunities"]["recent_missing_bars"] == 0
    assert data_status(result, bars[-1].bar_time + timedelta(minutes=1), START.date(), "open") == "ready"
    recent = [replace(b, partial=True) if i == len(bars) - 5 else b for i, b in enumerate(bars)]
    result = score(recent)
    assert result["opportunities"]["reference"]
    assert result["opportunities"]["filled_bars"] == 0
    assert data_status(result, bars[-1].bar_time + timedelta(minutes=1), START.date(), "open") == "gap"


def test_internal_flat_fill_is_causal_marked_and_does_not_mutate_source_or_invent_volume():
    original = candles([.001] * 20)
    bars = original[:6] + original[9:]
    before = deepcopy(bars)
    filled, coverage, reasons = analysis_window(bars)
    assert bars == before
    flat = [b for b in filled if not observed(b)]
    assert len(flat) == coverage["filled_bars"] == 3
    assert all(b.open == b.high == b.low == b.close == bars[5].close for b in flat)
    assert all(b.volume == 0 and b.turnover is None for b in flat)
    changed = bars[:6] + [replace(b, open=b.open * 2, high=b.high * 2, low=b.low * 2, close=b.close * 2)
                          for b in bars[6:]]
    assert [b.close for b in analysis_window(changed)[0] if not observed(b)] == [b.close for b in flat]
    assert coverage["filled_minutes"] == [b.bar_time.isoformat() for b in original[6:9]]
    assert any("成交量未知" in r for r in reasons)
    parsed = TrendResult.model_validate(score(bars))
    assert parsed.opportunities.filled_bars == parsed.structure.filled_bars == 3


def test_no_leading_trailing_future_or_cross_session_fills_and_stale_quotes_still_block():
    bars = candles([.0004] * 20)
    now = START + timedelta(minutes=30)
    result = calculate("SPY.US", bars[5:14], now)
    assert result["as_of"] == (START + timedelta(minutes=14)).isoformat()
    assert result["opportunities"]["filled_bars"] == 0
    assert result["opportunities"]["reference"]
    assert data_status(result, now, START.date(), "open") == "delayed"
    future = replace(bars[-1], bar_time=now + timedelta(minutes=2))
    assert calculate("SPY.US", bars[5:14] + [future], now) == result
    yesterday = candles([.001] * 60, start=START - timedelta(days=1))
    assert calculate("SPY.US", yesterday + bars[5:14], now) == result


def test_synthetic_close_cannot_confirm_breakout():
    bars = prices(oscillation() + [101.3, 101.4, 101.5])
    result = score(bars[:41] + bars[42:])
    assert not result["opportunities"]["reference"]
    assert result["opportunities"]["filled_bars"] == 1
    assert not result["opportunities"]["primary"]


def test_filled_input_evidence_freezes_across_history_repair_and_cannot_bypass_live_quote_checks():
    bars = prices(oscillation() + [101.3, 101.4])
    now = bars[-1].bar_time + timedelta(minutes=1, seconds=5)
    result = calculate("SPY.US", bars[:5] + bars[6:], now)
    branch = result["opportunities"]["primary"]
    price = branch["trigger"] + branch["atr"] * .5
    state, _ = transition({}, "SPY.US", result, quote(now - timedelta(seconds=31), price), now)
    assert not state.get("position")
    state, _ = transition({}, "SPY.US", result, quote(now, price), now)
    frozen = deepcopy(state["position"])
    assert frozen["version"] == "underlying_sim_v2"
    assert frozen["entry_evidence"]["analysis_coverage"]["filled_bars"] == 1
    repaired = calculate("SPY.US", bars, now + timedelta(seconds=5))
    state, events = transition(state, "SPY.US", repaired, quote(now + timedelta(seconds=5), price),
                               now + timedelta(seconds=5))
    assert state["position"]["entry_evidence"] == frozen["entry_evidence"]
    assert state["position"]["evidence"] == frozen["evidence"]
    assert not any(e["kind"] in {"entry", "exit"} for e in events)


def test_first_fifteen_minutes_and_last_sixty_minutes_have_distinct_boundaries():
    bars = candles([.0004] * 100)
    changed = [replace(b, close=Decimal(0)) if i < 40 else b for i, b in enumerate(bars)]
    assert score(changed)["opportunities"] == score(bars)["opportunities"]
    _, coverage, _ = analysis_window(bars[-14:])
    assert coverage["reference"] and coverage["recent_missing_bars"] == 1
    _, coverage, _ = analysis_window(bars[-15:])
    assert not coverage["reference"] and coverage["recent_available_bars"] == 15

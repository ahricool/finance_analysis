"""Chronological replay of unmodified session minutes and late confirmation evidence."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import transition
from tests.intraday_options.test_continuation import continuation, path
from tests.intraday_options.test_structure import prices
from tests.intraday_options.test_simulation import quote


@pytest.mark.parametrize("side", [1, -1])
def test_rejected_touch_cannot_appear_retroactively_after_rolling_or_restart(side):
    values = [100 + i * .1 for i in range(65)] + [105.55, 105.56, 105.6, 105.78, 105.87, 105.91]
    bars = [replace(b, high=max(b.open, b.close) + Decimal(".3"), low=min(b.open, b.close) - Decimal(".3"))
            for b in prices([100 + side * (v - 100) for v in values])]
    wick = "low" if side > 0 else "high"
    bars[40] = replace(bars[40], **{wick: getattr(bars[40], wick) - side * Decimal(".7")})
    state = {}
    restart_state = None
    seen = {}
    for i, bar in enumerate(bars):
        now = bar.bar_time + timedelta(minutes=1, seconds=5)
        result = calculate("SPY.US", bars[:i+1], now)
        q = quote(now, float(bar.close))
        if i == 70:
            # Cold computation after restoring the state saved at 10:40.
            rebuilt = calculate("SPY.US", list(bars), now)
            assert rebuilt == result
            restart_state, restart_events = transition(json.loads(json.dumps(state)), "SPY.US", rebuilt, q, now)
            assert not any(e["kind"] in {"confirmed", "entry"} for e in restart_events)
        state, events = transition(state, "SPY.US", result, q, now)
        for b in result["opportunities"]["branches"]:
            if b["kind"] == "trend_recovery":
                frozen = tuple(b[k] for k in ("process_id", "structure_start", "structure_end", "structure_high",
                                               "structure_low", "trigger", "invalidation", "atr"))
                if b["structure_id"] not in seen:
                    assert b["started_at"] == (bar.bar_time + timedelta(minutes=1)).isoformat()
                assert seen.setdefault(b["structure_id"], frozen) == frozen
        if i >= 65:
            rejected = (bars[65].bar_time + timedelta(minutes=1)).isoformat()
            assert all(b["started_at"] != rejected for b in result["opportunities"]["branches"])
            assert not any(e["kind"] in {"confirmed", "entry"} for e in events)
    assert len(seen) == 1 and restart_state == state


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("revision", [False, True])
@pytest.mark.parametrize("outside", [False, True])
def test_break_received_after_quote_needs_new_event(side, revision, outside):
    bars = path(side)
    closed = bars[-1].bar_time + timedelta(minutes=1)
    received = closed + timedelta(seconds=14)
    late = replace(bars[-1], received_at=received)
    versions = bars[:-1] + ([path(side, tail=(103.75,))[-1]] if revision else []) + [late]
    early = quote(closed + timedelta(seconds=3), float(late.close))
    before = calculate("SPY.US", versions, early.event_time)
    assert continuation(before)["confirmed_at"] is None
    state, _ = transition({}, "SPY.US", before, early, early.event_time)
    now = closed + timedelta(seconds=15)
    result = calculate("SPY.US", versions, now)
    state, events = transition(state, "SPY.US", result, early, now)
    assert not state.get("position") and not any(e["kind"] == "entry" for e in events)
    b = continuation(result)
    assert b["confirmed_at"] == closed.isoformat()
    assert b["confirmation_available_at"] == received.isoformat()
    assert "确认依据" in state["plans"][0]["execution_reason"]
    price = b["trigger"] + side * b["atr"] * (1.1 if outside else .5)
    fresh = quote(closed + timedelta(seconds=18), price)
    state, _ = transition(state, "SPY.US", result, fresh, closed + timedelta(seconds=20))
    if outside:
        assert not state.get("position") and "不在冻结执行区间" in state["plans"][0]["execution_reason"]
    else:
        assert state["position"]["entry_price_at"] == fresh.event_time.isoformat()
        assert state["position"]["entry_price"] == price


def test_confirmation_waits_for_late_structure_evidence_even_if_break_arrived_on_time():
    bars = path()
    closed = bars[-1].bar_time + timedelta(minutes=1)
    quote_at = closed + timedelta(seconds=3)
    received = closed + timedelta(seconds=14)
    # The missing piece is in the consolidation, not the confirming candle.
    bar = bars[-3]
    versions = [*bars[:-3], replace(bar, partial=True), replace(bar, received_at=received), *bars[-2:]]
    before = calculate("SPY.US", versions, quote_at)
    assert before["opportunities"]["primary"] is None
    now = closed + timedelta(seconds=15)
    result = calculate("SPY.US", versions, now)
    branch = continuation(result)
    assert branch["confirmed_at"] == closed.isoformat()
    assert branch["confirmation_available_at"] == received.isoformat()
    state, _ = transition({}, "SPY.US", result, quote(quote_at, 104), now)
    assert not state.get("position")

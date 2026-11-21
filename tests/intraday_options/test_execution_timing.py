"""Chronological replay of unmodified session minutes and late confirmation evidence."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from finance_analysis.intraday_options.rules import StartPolicy
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import transition
from tests.intraday_options.test_continuation import CONT_CFG, continuation, path
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
    recovery_cfg = StartPolicy(
        recovery_enabled=True,
        opening_enabled=False,
        midday_wave_enabled=False,
        minimum_risk_return=0.0,
        maximum_risk_return=0.0,
    )
    for i, bar in enumerate(bars):
        now = bar.bar_time + timedelta(minutes=1, seconds=5)
        result = calculate("SPY.US", bars[:i+1], now, settings=recovery_cfg)
        q = quote(now, float(bar.close))
        if i == 70:
            # Cold computation after restoring the state saved at 10:40.
            rebuilt = calculate("SPY.US", list(bars), now, settings=recovery_cfg)
            assert rebuilt == result
            restart_state, restart_events = transition(
                json.loads(json.dumps(state)), "SPY.US", rebuilt, q, now, settings=recovery_cfg
            )
            assert not any(e["kind"] in {"confirmed", "entry"} for e in restart_events)
        state, events = transition(state, "SPY.US", result, q, now, settings=recovery_cfg)
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
    before = calculate("SPY.US", versions, early.event_time, settings=CONT_CFG)
    assert continuation(before)["confirmed_at"] is None
    state, _ = transition({}, "SPY.US", before, early, early.event_time, settings=CONT_CFG)
    now = closed + timedelta(seconds=15)
    result = calculate("SPY.US", versions, now, settings=CONT_CFG)
    state, events = transition(state, "SPY.US", result, early, now, settings=CONT_CFG)
    assert not state.get("position") and not any(e["kind"] == "entry" for e in events)
    b = continuation(result)
    assert b["confirmed_at"] == closed.isoformat()
    assert b["confirmation_available_at"] == received.isoformat()
    assert "确认依据" in state["plans"][0]["execution_reason"]
    price = b["trigger"] + side * b["atr"] * (1.1 if outside else .5)
    fresh = quote(closed + timedelta(seconds=18), price)
    state, _ = transition(state, "SPY.US", result, fresh, closed + timedelta(seconds=20), settings=CONT_CFG)
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
    before = calculate("SPY.US", versions, quote_at, settings=CONT_CFG)
    assert before["opportunities"]["primary"] is None
    now = closed + timedelta(seconds=15)
    result = calculate("SPY.US", versions, now, settings=CONT_CFG)
    branch = continuation(result)
    assert branch["confirmed_at"] == closed.isoformat()
    assert branch["confirmation_available_at"] == received.isoformat()
    state, _ = transition({}, "SPY.US", result, quote(quote_at, 104), now, settings=CONT_CFG)
    assert not state.get("position")


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("outside", [False, True])
def test_late_revision_restores_entry_only_for_quotes_after_its_receipt(side, outside):
    bars = path(side, tail=(104, 104))
    closed = bars[-1].bar_time + timedelta(minutes=1)
    first = calculate("SPY.US", bars[:-1], closed - timedelta(seconds=55), settings=CONT_CFG)
    branch = continuation(first)
    identity = branch["structure_id"]
    inside = branch["trigger"] + side * .5 * branch["atr"]
    beyond = branch["trigger"] + side * 1.1 * branch["atr"]
    initial = quote(closed - timedelta(seconds=55), beyond)
    state, events = transition({}, "SPY.US", first, initial, initial.event_time, settings=CONT_CFG)
    frozen = state["confirmations"][identity]
    assert not state.get("position") and any(e["kind"] == "confirmed" for e in events)
    assert frozen["confirmed_at"] == (closed - timedelta(minutes=1)).isoformat()

    wick = "low" if side > 0 else "high"
    invalid = replace(bars[-1], **{wick: Decimal(str(branch["invalidation"])) - side * Decimal(".01")})
    received = closed + timedelta(seconds=14)
    revised = replace(bars[-1], received_at=received)
    versions = [*bars[:-1], invalid, revised]
    early = quote(closed + timedelta(seconds=3), inside)
    before = closed + timedelta(seconds=5)
    result = calculate("SPY.US", versions, before, settings=CONT_CFG)
    assert continuation(result)["status"] == "invalidated"
    prior_to_original = state
    state, _ = transition(state, "SPY.US", result, early, before, settings=CONT_CFG)
    assert not state.get("position")

    after = closed + timedelta(seconds=15)
    result = calculate("SPY.US", versions, after, settings=CONT_CFG)
    current = continuation(result)
    assert current["status"] == "confirmed" and current["confirmed_at"] == frozen["confirmed_at"]
    assert current["confirmation_available_at"] == frozen["confirmation_available_at"]
    assert current["execution_evidence_at"] == received.isoformat()
    missed_tick, _ = transition(prior_to_original, "SPY.US", result, early, after, settings=CONT_CFG)
    assert not missed_tick.get("position")
    state, events = transition(state, "SPY.US", result, early, after, settings=CONT_CFG)
    assert not state.get("position")
    assert not any(e["kind"] in {"entry", "confirmed"} for e in events)
    assert state["confirmations"][identity] == frozen
    plan = next(p for p in state["plans"] if p["structure_id"] == identity)
    assert plan["entry_quote_not_before"] == received.isoformat() and "确认依据" in plan["execution_reason"]
    # The next five-second check must keep the floor even after restoring persisted state.
    state, _ = transition(
        json.loads(json.dumps(state)), "SPY.US", result, early, after + timedelta(seconds=5), settings=CONT_CFG
    )
    assert not state.get("position")
    fresh = quote(closed + timedelta(seconds=23), beyond if outside else inside)
    state, events = transition(state, "SPY.US", result, fresh, closed + timedelta(seconds=25), settings=CONT_CFG)
    if outside:
        assert not state.get("position") and not any(e["kind"] == "entry" for e in events)
    else:
        assert state["position"]["entry_price_at"] == fresh.event_time.isoformat()
        assert state["position"]["entry_price"] == inside
        assert state["position"]["evidence"] == frozen


@pytest.mark.parametrize("side", [1, -1])
def test_continuous_confirmation_preserves_a_still_fresh_quote(side):
    bars = path(side, tail=(104, 104))
    closed = bars[-1].bar_time + timedelta(minutes=1)
    first_at = closed - timedelta(seconds=55)
    first = calculate("SPY.US", bars[:-1], first_at, settings=CONT_CFG)
    branch = continuation(first)
    outside = branch["trigger"] + side * 1.1 * branch["atr"]
    state, _ = transition({}, "SPY.US", first, quote(first_at, outside), first_at, settings=CONT_CFG)
    assert not state.get("position")
    # A new regular minute continues the already observed confirmation.
    q = quote(closed - timedelta(seconds=2), branch["trigger"] + side * .5 * branch["atr"])
    now = closed + timedelta(seconds=5)
    state, _ = transition(state, "SPY.US", calculate("SPY.US", bars, now, settings=CONT_CFG), q, now, settings=CONT_CFG)
    assert state["position"]["entry_price_at"] == q.event_time.isoformat()


@pytest.mark.parametrize("side", [1, -1])
def test_revision_does_not_delay_quote_when_original_minute_already_qualified(side):
    bars = path(side, tail=(104, 104))
    closed = bars[-1].bar_time + timedelta(minutes=1)
    before = closed + timedelta(seconds=5)
    first = calculate("SPY.US", bars, before, settings=CONT_CFG)
    branch = continuation(first)
    outside = branch["trigger"] + side * 1.1 * branch["atr"]
    state, _ = transition({}, "SPY.US", first, quote(before, outside), before, settings=CONT_CFG)
    assert branch["status"] == "confirmed" and not state.get("position")
    # The original qualified. Changing volume cannot restore eligibility that was never lost.
    revision = replace(bars[-1], volume=bars[-1].volume + 10, received_at=closed + timedelta(seconds=14))
    after = closed + timedelta(seconds=15)
    revised = calculate("SPY.US", [*bars, revision], after, settings=CONT_CFG)
    q = quote(closed + timedelta(seconds=12), branch["trigger"] + side * .5 * branch["atr"])
    state, _ = transition(state, "SPY.US", revised, q, after, settings=CONT_CFG)
    assert state["position"]["entry_price_at"] == q.event_time.isoformat()

"""Causal mechanisms, not a fit to any particular stock's historical drop."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from finance_analysis.interfaces.api.v1.schemas.intraday_options import TrendResult
from finance_analysis.intraday_options.analysis_window import analysis_window
from finance_analysis.intraday_options.rules import RULES, StartPolicy
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import plan, transition, statistics
from finance_analysis.intraday_options.structure import observed_atr
from tests.intraday_options.test_scoring import START
from tests.intraday_options.test_structure import oscillation, prices
from tests.intraday_options.test_simulation import quote


CONT_CFG = StartPolicy(
    continuation_enabled=True,
    box_enabled=True,
    opening_enabled=False,
    midday_wave_enabled=False,
    entry_window_minutes=150,
    minimum_risk_return=0.0,
    maximum_risk_return=0.0,
    min_open_move=0.0,
    pool_leader_top_k=0,
)


def score_cont(bars):
    return calculate(bars[0].symbol, bars, max(b.bar_time for b in bars) + timedelta(minutes=1), settings=CONT_CFG)


def path(side=1, tail=(104,)):
    values = [100 + i * .2 for i in range(20)] + [103.7, 103.72, 103.75] + list(tail)
    return prices([100 + side * (p - 100) for p in values])


def continuation(result):
    return next(b for b in result["opportunities"]["branches"] if b["kind"] == "trend_continuation"
                and not b.get("superseded_by"))


def execute(bars, side=1, previous=None, price=None):
    now = bars[-1].bar_time + timedelta(minutes=1, seconds=5)
    r = calculate("SPY.US", bars, now, settings=CONT_CFG)
    return r, now, transition(previous or {}, "SPY.US", r,
                              quote(now, float(bars[-1].close) if price is None else price), now, settings=CONT_CFG)


@pytest.mark.parametrize("side", [1, -1])
def test_strong_break_confirms_on_first_real_close_and_enters_at_live_quote(side):
    bars = path(side)
    before = continuation(score_cont(bars[:-1]))
    assert before["status"] == "forming" and before["confirmed_at"] is None
    result, now, (state, events) = execute(bars, side, price=float(bars[-1].close) - side * .01)
    branch = continuation(result)
    assert branch["status"] == "confirmed" and branch["confirmation_method"] == "strong_break"
    assert branch["confirmed_at"] == (now - timedelta(seconds=5)).isoformat()
    assert branch["structure_start"] == before["structure_start"]
    assert branch["structure_end"] == before["structure_end"]
    assert branch["trigger"] == before["trigger"]
    assert branch["atr_source"] == "observed_adjacent_true_ranges"
    assert branch["atr_samples"] >= 15
    assert state["position"]["side"] == side
    assert state["position"]["entry_price"] != float(bars[-1].close)
    assert state["position"]["target"] is None  # No made-up reward/risk target.
    assert state["plans"][0]["opportunity_valid"] and not state["plans"][0]["executable"]
    assert [e["kind"] for e in events].count("entry") == 1
    assert TrendResult.model_validate(result).opportunities.primary.confirmation_method == "strong_break"


@pytest.mark.parametrize("side", [1, -1])
def test_ordinary_break_still_needs_two_closes_and_freezes_confirmation_method(side):
    bars = path(side, (103.92, 103.93, 104))
    assert continuation(score_cont(bars[:-2]))["confirmed_at"] is None
    confirmed = continuation(score_cont(bars[:-1]))
    assert confirmed["status"] == "confirmed" and confirmed["confirmation_method"] == "two_closes"
    later = continuation(score_cont(bars))
    assert later["confirmed_at"] == confirmed["confirmed_at"]
    assert later["confirmation_method"] == "two_closes"


@pytest.mark.parametrize("side", [1, -1])
def test_oversized_break_is_not_chased_even_after_price_returns_to_execution_zone(side):
    bars = path(side, (105, 105.1))
    result, now, (state, _) = execute(bars, side)
    b = continuation(result)
    assert b["status"] == "extended" and b["breakout_rejection"]
    assert not state.get("position")
    price = b["trigger"] + side * .3 * b["atr"]
    assert not plan(b, result, price, now, settings=CONT_CFG)["executable"]
    assert "长K" in plan(b, result, price, now, settings=CONT_CFG)["execution_reason"]


def test_confirmed_is_not_executable_outside_frozen_interval_or_with_excess_structural_risk():
    bars = path()
    r = score_cont(bars); b = continuation(r); now = bars[-1].bar_time + timedelta(minutes=1)
    assert not plan(b, r, b["trigger"] + 1.1 * b["atr"], now, settings=CONT_CFG)["executable"]
    wide = {**b, "invalidation": b["trigger"] - 1.5 * b["atr"]}
    p = plan(wide, r, b["trigger"] + .7 * b["atr"], now, settings=CONT_CFG)
    assert not p["executable"] and "风险距离" in p["execution_reason"]
    assert RULES["trend_continuation"].max_risk_atr == 2


@pytest.mark.parametrize("side", [1, -1])
def test_ordinary_second_confirmation_cannot_evade_large_candle_guard(side):
    bars = path(side, (103.92, 103.93))
    field = "high" if side > 0 else "low"
    bars[-1] = replace(bars[-1], **{field: bars[-1].close + side})
    r, now, (state, _) = execute(bars, side)
    b = continuation(r)
    assert b["confirmed_at"] and b["breakout_rejection"]
    assert not plan(b, r, float(bars[-1].close), now, settings=CONT_CFG)["executable"]
    assert not state.get("position")


def test_choppy_background_and_continuous_impulse_do_not_manufacture_setups():
    for bars in (prices(oscillation() + [102, 104, 106]), prices([100 + i * .5 for i in range(60)])):
        assert not any(b["kind"] == "trend_continuation" for b in score_cont(bars)["opportunities"]["branches"])


@pytest.mark.parametrize("side", [1, -1])
def test_new_independent_pause_can_confirm_while_old_recovery_is_extended(side):
    recovery_cfg = StartPolicy(
        recovery_enabled=True,
        continuation_enabled=True,
        opening_enabled=False,
        midday_wave_enabled=False,
    )
    eval_bars = lambda xs: calculate("SPY.US", xs, max(b.bar_time for b in xs) + timedelta(minutes=1), settings=recovery_cfg)
    base = [100 + i * .1 for i in range(40)] + [103.05, 103.1, 103.15, 103.2, 103.3, 103.6, 103.9, 104.2]
    branches = eval_bars(prices([100 + side * (p - 100) for p in base]))["opportunities"]["branches"]
    old = next(b for b in branches if b["kind"] == "trend_recovery")
    assert old["kind"] == "trend_recovery" and old["status"] == "extended"
    bars = prices([100 + side * (p - 100) for p in base + [104.15, 104.16, 104.18, 104.38]])
    r = eval_bars(bars); new = continuation(r)
    assert new["status"] == "confirmed" and new["started_at"] < old["expires_at"]
    retained = next(b for b in r["opportunities"]["branches"] if b["structure_id"] == old["structure_id"])
    for field in ("trigger", "atr", "invalidation", "started_at", "confirmed_at"):
        assert retained[field] == old[field]


@pytest.mark.parametrize("side", [1, -1])
def test_recovery_replacement_requires_new_real_advance_then_counter_move(side):
    recovery_cfg = StartPolicy(recovery_enabled=True, opening_enabled=False, midday_wave_enabled=False)
    eval_bars = lambda xs: calculate("SPY.US", xs, max(b.bar_time for b in xs) + timedelta(minutes=1), settings=recovery_cfg)
    base = [100 + i * .1 for i in range(40)] + [103.05, 103.1, 103.15, 103.2, 103.3]
    convert = lambda values: prices([100 + side * (p - 100) for p in values])
    old = eval_bars(convert(base))["opportunities"]["primary"]
    assert old["kind"] == "trend_recovery"
    continuous = eval_bars(convert(base + [103.6, 103.9, 104.2]))["opportunities"]["branches"]
    assert len([b for b in continuous if b["kind"] == "trend_recovery"]) == 1
    rebuilt = eval_bars(convert(base + [103.6, 103.9, 104.2, 103.4]))["opportunities"]["branches"]
    recoveries = [b for b in rebuilt if b["kind"] == "trend_recovery"]
    assert len(recoveries) == 2
    retained = next(b for b in recoveries if b["structure_id"] == old["structure_id"])
    new = next(b for b in recoveries if b["structure_id"] != old["structure_id"])
    assert retained["superseded_by"] == new["structure_id"]
    assert retained["trigger"] == old["trigger"] and retained["atr"] == old["atr"]
    assert new["structure_start"] > old["structure_end"]
    assert new["started_at"] < old["expires_at"]


def test_real_volatility_samples_do_not_include_flat_fills_or_gap_spanning_moves():
    bars = prices([100 + i * .2 for i in range(35)])
    full, _ = observed_atr(bars)
    missing = bars[:5] + bars[9:]
    filled, coverage, _ = analysis_window(missing)
    assert coverage["filled_bars"] == 4
    actual, count = observed_atr(filled)
    assert actual == pytest.approx(full) and count >= 15
    assert observed_atr(analysis_window(bars[:5] + bars[25:])[0])[0] is None


def test_flat_pause_and_unclosed_or_future_break_do_not_confirm():
    bars = path()
    now = bars[-1].bar_time
    before = calculate("SPY.US", bars[:-1], now, settings=CONT_CFG)
    assert calculate("SPY.US", bars, now, settings=CONT_CFG) == before
    assert calculate("SPY.US", bars[:-1] + [replace(bars[-1], confirmed=False)], now, settings=CONT_CFG) == before
    gap = score_cont(bars[:21] + bars[22:])
    assert not any(b["kind"] == "trend_continuation" for b in gap["opportunities"]["branches"])
    # A missing second ordinary confirmation cannot be replaced with a flat bar.
    normal = path(tail=(103.92, 103.93, 103.94))
    assert continuation(score_cont(normal[:-2] + normal[-1:]))["confirmed_at"] is None


def test_restart_multi_branch_and_revision_cannot_change_entry_evidence_or_repeat_trade():
    bars = path(); r, now, (state, events) = execute(bars)
    frozen = deepcopy(state["position"])
    revised = deepcopy(r)
    b = revised["opportunities"]["branches"][0]
    b.update(atr=10, trigger=50, invalidation=20, confirmation_method="two_closes")
    state, again = transition(deepcopy(state), "SPY.US", revised, quote(now + timedelta(seconds=5), 104),
                              now + timedelta(seconds=5), settings=CONT_CFG)
    assert state["position"]["entry_evidence"] == frozen["entry_evidence"]
    # Linked alternate branch has the same process and cannot enter after exit.
    linked = {**r["opportunities"]["branches"][0], "kind": "trend_recovery", "structure_id": "linked"}
    r["opportunities"]["branches"].append(linked)
    later = now + timedelta(seconds=10)
    state, exit_events = transition(state, "SPY.US", r, quote(later, frozen["invalidation"] - .01), later,
                                    settings=CONT_CFG)
    assert sum(e["kind"] == "exit" for e in exit_events) == 1
    assert not any(e["kind"] == "entry" for e in exit_events)
    state, replay = transition(deepcopy(state), "SPY.US", r, quote(later + timedelta(seconds=5), 104),
                               later + timedelta(seconds=5), settings=CONT_CFG)
    assert not state.get("position") and not any(e["kind"] in {"entry", "exit"} for e in replay)
    groups = statistics([next(e["trade"] for e in exit_events if e["kind"] == "exit")])
    assert next(g for g in groups if g["label"] == "trend_continuation/1")["count"] == 1


def test_new_structure_can_trade_before_previous_observation_lifetime_expires():
    bars = path(); r, now, (state, _) = execute(bars)
    old = deepcopy(state["position"])
    later = now + timedelta(seconds=5)
    state, _ = transition(state, "SPY.US", r, quote(later, old["invalidation"] - .01), later, settings=CONT_CFG)
    # Actual new observed impulse + pause (not a shifted timestamp of the same pause).
    extended = path(tail=(104, 104.2, 104.4, 104.35, 104.36, 104.38, 104.6))
    # Within daily cap / cooldown windows, V6 blocks immediate re-entry.
    _, _, (cooled, _) = execute(extended, previous=state)
    assert not cooled.get("position")
    # Once daily cap & cooldown windows are cleared, the independent new structure can trade without process conflict.
    uncooled = deepcopy(state)
    uncooled["daily_entry_count"] = 0
    uncooled["last_exit_at"] = (now - timedelta(minutes=70)).isoformat()
    uncooled["last_stop_by_side"] = {}
    nr, nnow, (state, events) = execute(extended, previous=uncooled)
    assert state["position"] and state["position"]["process_id"] != old["process_id"]
    assert nnow.isoformat() < old["entry_evidence"]["expires_at"]
    assert sum(e["kind"] == "entry" for e in events) == 1


def test_prefix_replay_and_future_data_keep_frozen_structure_and_confirmation():
    bars = path(tail=(104, 104.2, 104.4, 104.35, 104.36, 104.38, 104.6))
    seen = {}
    for end in range(19, len(bars) + 1):
        now = bars[end - 1].bar_time + timedelta(minutes=1)
        r = calculate("SPY.US", bars[:end], now, settings=CONT_CFG)
        assert calculate("SPY.US", bars, now, settings=CONT_CFG) == r
        for b in r["opportunities"]["branches"]:
            if b["kind"] != "trend_continuation":
                continue
            evidence = tuple(b[k] for k in ("process_id", "structure_start", "structure_end", "structure_high",
                                            "structure_low", "trigger", "invalidation", "atr"))
            assert seen.setdefault(b["structure_id"], evidence) == evidence


def test_quote_staleness_cutoff_and_existing_legacy_position_still_block_new_entries():
    bars = path(); r = score_cont(bars); now = bars[-1].bar_time + timedelta(minutes=1, seconds=5)
    state, _ = transition({}, "SPY.US", r, quote(now - timedelta(seconds=31), 104), now, settings=CONT_CFG)
    assert not state.get("position")
    cutoff = START.replace(hour=17, minute=0)
    assert not transition({}, "SPY.US", r, quote(cutoff, 104), cutoff, settings=CONT_CFG)[0].get("position")
    state, _ = transition({}, "SPY.US", r, quote(now, 104), now, settings=CONT_CFG)
    state["position"]["version"] = "underlying_sim_v2"
    frozen = deepcopy(state["position"])
    later = now + timedelta(seconds=5)
    state, events = transition(state, "SPY.US", r, quote(later, 104), later, settings=CONT_CFG)
    assert state["position"]["version"] == "underlying_sim_v2"
    assert state["position"]["entry_evidence"] == frozen["entry_evidence"]
    assert not any(e["kind"] == "entry" for e in events)


def test_invalidated_recovery_requires_independent_new_price_behavior_before_replacement():
    recovery_cfg = StartPolicy(recovery_enabled=True, opening_enabled=False, midday_wave_enabled=False)
    eval_bars = lambda xs: calculate("SPY.US", xs, max(b.bar_time for b in xs) + timedelta(minutes=1), settings=recovery_cfg)
    base = [100 + i * .1 for i in range(40)] + [103.05, 102.5]
    old = next(b for b in eval_bars(prices(base))["opportunities"]["branches"] if b["kind"] == "trend_recovery")
    assert old["status"] == "invalidated"
    same = eval_bars(prices(base + [102.5] * 3))["opportunities"]["branches"]
    assert len([b for b in same if b["kind"] == "trend_recovery"]) == 1
    new = eval_bars(prices(base + [103.2, 103.5, 103.8, 104.1, 103.3]))["opportunities"]["branches"]
    recoveries = [b for b in new if b["kind"] == "trend_recovery"]
    assert len(recoveries) == 2
    assert next(b for b in recoveries if b["structure_id"] == old["structure_id"])["invalidation"] == old["invalidation"]


def test_extended_continuation_can_recover_using_original_levels_without_rebuilding():
    bars = path(tail=(104, 104.2, 104.4, 104.01))
    extended = continuation(score_cont(bars[:-1]))
    restored = continuation(score_cont(bars))
    assert extended["status"] == "extended" and restored["status"] == "confirmed"
    for key in ("structure_id", "trigger", "atr", "invalidation", "confirmed_at"):
        assert extended[key] == restored[key]


def test_consolidation_cannot_wait_forever_or_refresh_its_boundaries():
    bars = path(tail=(103.74, 103.75, 103.74, 103.75, 103.74))
    frozen = continuation(score_cont(bars[:23]))
    later = continuation(score_cont(bars))
    assert later["status"] == "expired"
    assert later["structure_id"] == frozen["structure_id"]
    assert later["trigger"] == frozen["trigger"]
    assert len([b for b in score_cont(bars)["opportunities"]["branches"] if b["kind"] == "trend_continuation"]) == 1


def test_sliding_hour_does_not_recompute_old_id_with_shortened_background():
    values = [100 + i * .1 for i in range(40)] + [103.05, 103.1, 103.15, 103.2, 103.3]
    values += [103.3 + i * .1 for i in range(70)]
    seen = {}
    for end in range(40, len(values) + 1):
        for b in score_cont(prices(values[:end]))["opportunities"]["branches"]:
            evidence = tuple(b.get(k) for k in ("process_id", "structure_start", "structure_end", "structure_high",
                                                "structure_low", "trigger", "invalidation", "atr", "started_at"))
            assert seen.setdefault(b["structure_id"], evidence) == evidence

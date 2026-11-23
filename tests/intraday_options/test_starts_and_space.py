"""Causal opening/swing entries and quote-time execution economics."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from finance_analysis.intraday_options.analysis_window import FLAT_SOURCE
from finance_analysis.intraday_options.opportunities import calculate_opportunities
from finance_analysis.intraday_options.rules import StartPolicy
from finance_analysis.intraday_options.runtime import ranked_opportunity
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import plan, target_space, transition
from tests.intraday_options.test_scoring import START
from tests.intraday_options.test_structure import prices
from tests.intraday_options.test_simulation import NOW, quote, result


LEGACY_POLICY = StartPolicy(
    pivot_enabled=True,
    midday_wave_enabled=False,
    box_enabled=True,
    continuation_enabled=True,
    use_pivot_target=True,
    opening_min_elapsed_minutes=5,
    opening_min_efficiency=0.0,
    opening_require_directional_bar=False,
    opening_direction_mode="both",
    exclude_benchmark_from_opening=False,
    entry_window_minutes=150,
    atr_scaled_exits=False,
    stop_loss_pct=0.0,
    take_profit_pct=0.0,
    profit_lock_trigger_pct=0.0,
    profit_lock_level_pct=0.0,
    minimum_return=0.001,
    minimum_rr=0.5,
    minimum_risk_return=0.0,
    maximum_risk_return=0.0,
    opening_min_range_pct=0.0,
    min_gap_directional=None,
    min_open_move=0.0,
    min_spy_open_move=0.0,
    min_pool_breadth=0.0,
    pool_leader_top_k=0,
)


def ramp(count, side=1, step=.22):
    bars = prices([100 + side * i * step for i in range(count)])
    return [replace(b, high=max(b.open, b.close) + Decimal(".001"),
                    low=min(b.open, b.close) - Decimal(".001")) for b in bars]


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("minutes", [5, 15])
def test_opening_first_close_executes_without_consolidation_and_can_stop_immediately(side, minutes):
    bars = ramp(minutes + 1, side)
    config = StartPolicy(
        opening_minutes=minutes,
        opening_min_elapsed_minutes=minutes,
        opening_min_efficiency=0.0,
        opening_require_directional_bar=False,
        opening_direction_mode="both",
        exclude_benchmark_from_opening=False,
        entry_window_minutes=150,
        atr_scaled_exits=False,
        stop_loss_pct=0.0,
        take_profit_pct=0.0,
        profit_lock_trigger_pct=0.0,
        profit_lock_level_pct=0.0,
        minimum_risk_return=0.0,
        maximum_risk_return=0.0,
        min_gap_directional=None,
        min_open_move=0.0,
        min_spy_open_move=0.0,
        min_pool_breadth=0.0,
        pool_leader_top_k=0,
    )
    assert not calculate_opportunities(bars[:-1], config)["branches"]
    o = calculate_opportunities(bars, config)
    b = next(b for b in o["branches"] if b["kind"] == "opening_breakout")
    now = START + timedelta(minutes=minutes + 1, seconds=2)
    assert b["confirmed_at"] == (now - timedelta(seconds=2)).isoformat()
    assert b["confirmation_method"] == "strong_break"
    assert b["atr_samples"] == minutes - 1 and b["structure_end"] == bars[-1].bar_time.isoformat()
    assert o["reference"] == (minutes == 5)
    r = dict(trading_date=now.date().isoformat(), as_of=o["as_of"], opportunities=o)
    price = b["trigger"] + side * .5 * b["atr"]
    far = b["trigger"] + side * 11.0 * b["atr"]
    state, events = transition({}, "SPY.US", r, quote(now, far), now, settings=config)
    assert not state.get("position") and not any(e["kind"] == "entry" for e in events)
    state, events = transition(state, "SPY.US", r, quote(now, price), now, settings=config)
    assert state["position"]["entry_price"] == price and ranked_opportunity(r, state, now)
    assert state["position"]["entry_evidence"]["target_source"] == "移动止损跟踪"
    t = now + timedelta(seconds=5)
    state, events = transition(state, "SPY.US", r, quote(t, b["invalidation"] - side * .01), t, settings=config)
    assert [e["kind"] for e in events] == ["exit"]
    # Persisted state cannot consume the same opening leg a second time.
    t += timedelta(seconds=5)
    state, events = transition(json.loads(json.dumps(state)), "SPY.US", r, quote(t, price), t, settings=config)
    assert not state.get("position") and not any(e["kind"] == "entry" for e in events)
    assert not any(b["kind"] == "opening_breakout" for b in calculate_opportunities(ramp(30, side), config)["branches"])


@pytest.mark.parametrize("damage", ["gap", "synthetic", "unclosed", "late"])
def test_opening_requires_original_observations(damage):
    bars = ramp(6)
    if damage == "gap":
        bars.pop(2)
    elif damage == "synthetic":
        bars[2] = replace(bars[2], source=FLAT_SOURCE)
    elif damage == "unclosed":
        bars[2] = replace(bars[2], confirmed=False)
    else:
        bars[2] = replace(bars[2], received_at=START + timedelta(minutes=7))
    r = calculate("SPY.US", bars, START + timedelta(minutes=6, seconds=3))
    assert not any(b["kind"] == "opening_breakout" for b in r["opportunities"]["branches"])


@pytest.mark.parametrize("side", [1, -1])
def test_pivot_known_before_break_no_box_and_one_identity(side):
    seq = [100 + .08*i for i in range(16)] + [101.1, 101.03, 101.08, 101.34, 101.42, 101.5]
    bars = prices([100 + side * (v-100) for v in seq])
    config = StartPolicy(opening_enabled=False, pivot_enabled=True, midday_wave_enabled=False)
    def pivot(xs):
        return [b for b in calculate_opportunities(xs, config)["branches"] if b["kind"] == "pivot_breakout"]
    assert not pivot(bars[:18])
    branch, = pivot(bars[:20])
    assert branch["trigger"] == pytest.approx(100 + side * 1.25)
    assert branch["structure_end"] < branch["confirmed_at"] and branch["atr_samples"] >= 10
    assert [b["process_id"] for b in pivot(bars)] == [branch["process_id"]]
    assert not pivot(bars[:15] + bars[16:])
    assert not pivot(bars[:16] + [replace(bars[16], source=FLAT_SOURCE)] + bars[17:])
    # Late revision in a swing wing was not evidence before the historical break.
    late = list(bars)
    late[16] = replace(late[16], received_at=bars[-1].received_at)
    assert not pivot(late)


@pytest.mark.parametrize("side", [1, -1])
def test_independent_gates_and_inclusive_boundaries(side):
    def reasons(price, risk, space):
        cfg = StartPolicy(use_pivot_target=True, minimum_return=0.001, minimum_rr=1.0)
        return target_space(price, price-side*risk, price+side*space, side, True, cfg)["space_rejections"]
    assert reasons(100, .01, .02) == ["剩余止盈幅度不足"]
    assert reasons(100, 1.25, .25) == ["计划盈亏比不足"]
    assert not reasons(100, .1, .1)
    assert reasons(100.5, 1.25, .01) == ["剩余止盈幅度不足", "计划盈亏比不足"]
    assert target_space(100.5, 100.5-side*1.25, 100.5+side*.01, side, True, LEGACY_POLICY)["reward_risk"] == pytest.approx(.008)
    assert reasons(100, 0, .1)[0].startswith("初始风险无效")
    assert reasons(100, 1, 0) == ["目标已越过"]


def test_nearest_blocked_target_retry_other_branch_and_fast_normal_exit():
    r = result()
    b = r["opportunities"]["branches"][0]
    b.update(invalidation=99.25, quality_score=99, started_at=NOW.isoformat())
    r["execution_pivots"] = [dict(kind="high", price=v, confirmed_at=NOW.isoformat()) for v in (103, 100.51)]
    state, events = transition({}, "SPY.US", r, quote(), NOW, settings=LEGACY_POLICY)
    p = state["plans"][0]
    assert p["target"] == 100.51 and len(p["space_rejections"]) == 2
    assert not ranked_opportunity(r, state, NOW) and not any(e["kind"] == "entry" for e in events)
    t = NOW + timedelta(seconds=5)
    state, _ = transition(state, "SPY.US", r, quote(t, 100.6), t, settings=LEGACY_POLICY)
    assert state["plans"][0]["target"] == 100.51 and "目标已越过" in state["plans"][0]["execution_reason"]
    # Other branch uses its own independent direction/target; blocked higher quality does not veto it.
    alt = deepcopy(b)
    alt.update(kind="trend_recovery", direction="bearish", structure_id="other", process_id="other",
               trigger=101, invalidation=101.5, measurement_target=98, quality_score=60)
    r["opportunities"]["branches"].append(alt)
    t += timedelta(seconds=5)
    state, events = transition(state, "SPY.US", r, quote(t, 100.5), t, settings=LEGACY_POLICY)
    assert ranked_opportunity(r, state, t)["structure_id"] == "other"
    entry, = [e for e in events if e["kind"] == "entry"]
    assert entry["trade"]["entry_evidence"]["reward_risk"] == 2.5
    t += timedelta(seconds=35)
    state, events = transition(state, "SPY.US", r, quote(t, 98), t, settings=LEGACY_POLICY)
    trade = next(e["trade"] for e in events if e["kind"] == "exit")
    assert trade["duration_seconds"] == 35 and trade["exit_reason"] == "到达目标"


def test_quote_improvement_rechecks_interval_expiry_freshness_and_structure_dedup():
    r = result()
    b = r["opportunities"]["branches"][0]
    b.update(measurement_target=101.4, invalidation=99.25, quality_score=80)
    state, _ = transition({}, "SPY.US", r, quote(price=100.8), NOW, settings=LEGACY_POLICY)
    assert not state.get("position") and state["plans"][0]["space_rejections"] == ["计划盈亏比不足"]
    t = NOW + timedelta(seconds=5)
    for invalid_quote in (quote(t, 100.1), quote(t-timedelta(seconds=31), 100.3)):
        waiting, _ = transition(state, "SPY.US", r, invalid_quote, t, settings=LEGACY_POLICY)
        assert not waiting.get("position")
    assert not plan(b, r, 100.3, NOW+timedelta(minutes=15), settings=LEGACY_POLICY)["executable"]
    alt = dict(b, kind="pivot_breakout", quality_score=50, structure_id="swing", process_id="swing",
               structure_start=(t-timedelta(minutes=5)).isoformat(), structure_end=NOW.isoformat())
    r["opportunities"]["branches"].append(alt)
    state, _ = transition(state, "SPY.US", r, quote(t, 100.3), t, settings=LEGACY_POLICY)
    assert state["position"]["entry_evidence"]["entry_quote"] == 100.3
    t += timedelta(seconds=5)
    state, _ = transition(state, "SPY.US", r, quote(t, 101.7), t, settings=LEGACY_POLICY)
    t += timedelta(seconds=5)
    state, events = transition(json.loads(json.dumps(state)), "SPY.US", r, quote(t, 100.3), t, settings=LEGACY_POLICY)
    assert not state.get("position") and not any(e["kind"] == "entry" for e in events)
    for kind, allowed in (("pivot_breakout", False), ("trend_continuation", True)):
        other = dict(b, kind=kind, measurement_target=None)
        assert plan(other, r, 100.3, t, settings=LEGACY_POLICY)["executable"] == allowed


def test_observed_opening_boundaries_survive_revision_before_break_and_restart():
    # 12 bars (09:30..09:41 -> closes 09:42 NY) with +3.85% clean move (eff=1.0) triggers V8 long-only opening drive.
    bars = [replace(b, symbol="NVDA.US") for b in ramp(12, step=.35)]
    now = START + timedelta(minutes=5, seconds=2)
    r = calculate("NVDA.US", bars[:5], now)
    state, _ = transition({}, "NVDA.US", r, quote(now, 101.4), now)
    frozen = deepcopy(state["start_levels"])
    assert len(frozen) == 1
    revised = replace(bars[4], high=bars[4].high+Decimal(".005"), received_at=now+timedelta(seconds=10))
    now = START + timedelta(minutes=12, seconds=2)
    r = calculate("NVDA.US", [*bars[:5], revised, *bars[5:]], now)
    b = r["opportunities"]["primary"]
    assert b is not None
    price = b["trigger"]+.5*b["atr"]
    state, events = transition(json.loads(json.dumps(state)), "NVDA.US", r, quote(now, price), now)
    assert state["start_levels"] == frozen and not state.get("position")
    assert "冻结结构" in state["plans"][0]["execution_reason"] and not ranked_opportunity(r, state, now)
    assert not any(e["kind"] == "entry" for e in events)


def test_rank_rechecks_new_quote_before_next_tick_and_keeps_blocked_reason_on_alternate_entry():
    r = result()
    high = r["opportunities"]["branches"][0]
    high.update(quality_score=90, measurement_target=102)
    other = dict(high, structure_id="other", process_id="other", quality_score=60, measurement_target=100.51)
    r["opportunities"]["branches"].append(other)
    state, _ = transition({}, "SPY.US", r, quote(), NOW, settings=LEGACY_POLICY)
    assert "剩余止盈幅度不足" in state["plans"][1]["execution_reason"]
    assert ranked_opportunity(r, state, NOW, quote())["structure_id"] == high["structure_id"]
    t = NOW + timedelta(seconds=1)
    assert not ranked_opportunity(r, state, t, quote(t, 102.1))
    assert not ranked_opportunity(r, state, t, quote(t-timedelta(seconds=31)))


def test_old_consumed_window_without_entry_timestamp_and_transient_missing_plan():
    from finance_analysis.intraday_options.simulation import consumed_structure
    r = result()
    b = r["opportunities"]["branches"][0]
    window = {"direction": "bullish", "family": "box", "start": NOW.isoformat(), "end": b["expires_at"]}
    assert consumed_structure(dict(b, kind="pivot_breakout"), window)
    r["execution_pivots"] = [dict(kind="high", price=v, confirmed_at=NOW.isoformat()) for v in (100.51, 103)]
    state, _ = transition({}, "SPY.US", r, quote(), NOW, settings=LEGACY_POLICY)
    t = NOW + timedelta(seconds=5)
    state, _ = transition(state, "SPY.US", None, None, t, settings=LEGACY_POLICY)
    t += timedelta(seconds=5)
    state, _ = transition(json.loads(json.dumps(state)), "SPY.US", r, quote(t, 100.6), t, settings=LEGACY_POLICY)
    assert state["plans"][0]["target"] == 100.51 and not state.get("position")

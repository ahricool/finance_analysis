"""V5 intraday strategy optimization tests: wave capture, noise reduction and risk controls."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from finance_analysis.interfaces.api.v1.schemas.intraday_options import TrendResult
from finance_analysis.intraday_options.rules import ENTRY_VERSION, SIMULATION_VERSION, StartPolicy, policy
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import plan, transition
from finance_analysis.intraday_options.structure import execution_context
from finance_analysis.market_stream.session import session_bounds
from tests.intraday_options.test_scoring import START, candles
from tests.intraday_options.test_simulation import NOW, quote, result


def _make_bars(values, symbol="NVDA.US", start=START, wick=Decimal("0.01")):
    bars = candles([0] * len(values), symbol=symbol, start=start)
    for i, val in enumerate(values):
        prev = values[max(0, i - 1)]
        hi = Decimal(str(max(prev, val))) + wick
        lo = Decimal(str(min(prev, val))) - wick
        bars[i] = replace(
            bars[i],
            open=Decimal(str(prev)),
            close=Decimal(str(val)),
            high=hi,
            low=lo,
        )
    return bars


def test_v5_policy_defaults_disable_noisy_branches_and_pivot_truncation(monkeypatch):
    for key in (
        "INTRADAY_OPENING_BREAKOUT",
        "INTRADAY_PIVOT_BREAKOUT",
        "INTRADAY_MIDDAY_WAVE_BREAKOUT",
        "INTRADAY_TREND_RECOVERY",
        "INTRADAY_USE_PIVOT_TARGET",
        "INTRADAY_MIN_TARGET_RETURN",
        "INTRADAY_MIN_REWARD_RISK",
        "INTRADAY_MIN_RISK_RETURN",
        "INTRADAY_REQUIRE_VWAP",
        "INTRADAY_REQUIRE_SPY_ALIGNMENT",
        "INTRADAY_MIN_RELATIVE_STRENGTH",
    ):
        monkeypatch.delenv(key, raising=False)
    policy.cache_clear()
    try:
        cfg = policy()
        assert cfg.opening_enabled is True
        assert cfg.midday_wave_enabled is True
        assert cfg.pivot_enabled is False
        assert cfg.recovery_enabled is False
        assert cfg.use_pivot_target is False
        assert cfg.minimum_return == 0.0
        assert cfg.minimum_rr == 0.0
        assert cfg.minimum_risk_return == pytest.approx(0.003)
        assert cfg.require_vwap is True
        assert cfg.require_spy_alignment is True
        assert cfg.min_relative_strength == pytest.approx(0.002)
        assert ENTRY_VERSION == "intraday_entry_v5"
        assert SIMULATION_VERSION == "underlying_sim_v5"
    finally:
        policy.cache_clear()


@pytest.mark.parametrize("side", [1, -1])
def test_opening_range_width_filter_and_two_close_vs_strong_bar_confirmation(side):
    # Narrow opening range (< 0.35%) is ignored.
    narrow = _make_bars([100 + side * i * 0.04 for i in range(7)], wick=Decimal("0.001"))
    r_narrow = calculate("NVDA.US", narrow, narrow[-1].bar_time + timedelta(minutes=1, seconds=2))
    assert not any(b["kind"] == "opening_breakout" for b in r_narrow["opportunities"]["branches"])

    # Wide opening range (>= 0.35%) with weak breakout bar (long wick -> body fraction < 60%) waits for 2nd close.
    base = [100 + side * i * 0.12 for i in range(5)]  # range ~0.48%
    bars = _make_bars(base + [base[-1] + side * 0.05, base[-1] + side * 0.09], wick=Decimal("0.001"))
    # Give bar 5 a large wick so body_fraction < 0.60 and distance is between 0.20 and 0.40 ATR.
    bars[5] = replace(
        bars[5],
        high=bars[5].high + Decimal("0.20"),
        low=bars[5].low - Decimal("0.20"),
    )
    first_at = bars[5].bar_time + timedelta(minutes=1, seconds=2)
    r1 = calculate("NVDA.US", bars[:6], first_at)
    b1 = next(b for b in r1["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    assert b1["status"] == "forming" and b1["confirmed_at"] is None

    second_at = bars[6].bar_time + timedelta(minutes=1, seconds=2)
    r2 = calculate("NVDA.US", bars, second_at)
    b2 = next(b for b in r2["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    assert b2["status"] == "confirmed" and b2["confirmation_method"] == "two_closes"
    assert b2["confirmed_at"] == (bars[6].bar_time + timedelta(minutes=1)).isoformat()

    # Opening level stays alive up to 85 minutes after OR freezes (e.g. breakout at 10:45 NY).
    sideways = base + [base[-1] - side * 0.10 if i % 2 else base[-1] - side * 0.05 for i in range(65)]
    delayed = _make_bars(sideways + [base[-1] + side * 0.25], wick=Decimal("0.001"))
    r_delayed = calculate("NVDA.US", delayed, delayed[-1].bar_time + timedelta(minutes=1, seconds=2))
    b_del = next(b for b in r_delayed["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    assert b_del["status"] == "confirmed" and b_del["confirmation_method"] == "strong_break"


@pytest.mark.parametrize("side", [1, -1])
def test_midday_wave_breakout_detection_causality_and_rolling_identity(side):
    # 40-minute sideways consolidation (~1.5% width) followed by a clean midday wave breakout.
    coil = [100 + side * (0.75 * (1 if i % 4 in (1, 2) else -1)) for i in range(40)]
    breakout = [100 + side * 1.15, 100 + side * 1.35]
    bars = _make_bars(coil + breakout, symbol="NVDA.US", wick=Decimal("0.02"))
    now = bars[-1].bar_time + timedelta(minutes=1, seconds=2)
    res = calculate("NVDA.US", bars, now)
    TrendResult.model_validate(res)
    midday = [b for b in res["opportunities"]["branches"] if b["kind"] == "midday_wave_breakout"]
    assert len(midday) == 1
    branch = midday[0]
    assert branch["status"] == "confirmed"
    assert branch["direction"] == ("bullish" if side == 1 else "bearish")
    assert branch["confirmation_method"] in {"strong_break", "two_closes"}
    assert branch["atr_source"] == "observed_adjacent_true_ranges"

    # Rolling replay preserves exact frozen identity and trigger across subsequent minutes.
    extended_vals = coil + breakout + [100 + side * 1.40, 100 + side * 1.45]
    extended = _make_bars(extended_vals, symbol="NVDA.US", wick=Decimal("0.02"))
    res_later = calculate("NVDA.US", extended, extended[-1].bar_time + timedelta(minutes=1, seconds=2))
    later = next(b for b in res_later["opportunities"]["branches"] if b["structure_id"] == branch["structure_id"])
    for key in ("trigger", "invalidation", "atr", "started_at", "confirmed_at", "structure_start", "structure_end"):
        assert later[key] == branch[key]

    # Late revision inside the consolidation window cannot retroactively manufacture a historical break.
    late = list(bars)
    late[20] = replace(late[20], received_at=bars[-1].bar_time + timedelta(minutes=2))
    res_late = calculate("NVDA.US", late, bars[-1].bar_time + timedelta(minutes=2, seconds=5))
    assert not any(b["kind"] == "midday_wave_breakout" for b in res_late["opportunities"]["branches"])


def test_vwap_spy_alignment_relative_strength_and_min_risk_gates():
    # Build NVDA strong bullish opening breakout (~1.0% up, ~1.2 ATR beyond OR high -> confirmed, not extended).
    nvda_vals = [100.0, 100.2, 100.4, 100.6, 100.8, 101.05]
    nvda_bars = _make_bars(nvda_vals, symbol="NVDA.US", wick=Decimal("0.02"))
    spy_strong = _make_bars([500.0, 500.4, 500.8, 501.2, 501.6, 502.1], symbol="SPY.US", wick=Decimal("0.02"))
    spy_weak = _make_bars([500.0, 499.8, 499.6, 499.5, 499.4, 499.2], symbol="SPY.US", wick=Decimal("0.02"))
    spy_faster = _make_bars([500.0, 502.0, 504.0, 506.0, 508.0, 512.0], symbol="SPY.US", wick=Decimal("0.02"))

    now = nvda_bars[-1].bar_time + timedelta(minutes=1, seconds=5)
    base = calculate("NVDA.US", nvda_bars, now)
    b = next(x for x in base["opportunities"]["branches"] if x["kind"] == "opening_breakout")
    assert b["status"] == "confirmed"
    price = b["trigger"] + 1.0 * b["atr"]
    assert (price - b["invalidation"]) / price >= 0.003

    # 1. All gates pass: NVDA > VWAP, SPY > SPY VWAP, RS = +1.4% - 0.36% = +1.04% >= 0.20%, risk >= 30bp.
    r_ok = {**base, **execution_context(nvda_bars, spy_strong)}
    p_ok = plan(b, r_ok, price, now, now)
    assert p_ok["executable"] and p_ok["target"] is None and p_ok["target_source"] == "移动止损跟踪"

    # 2. SPY below VWAP blocks long entry.
    r_spy_down = {**base, **execution_context(nvda_bars, spy_weak)}
    p_spy_down = plan(b, r_spy_down, price, now, now)
    assert not p_spy_down["executable"] and "SPY" in p_spy_down["execution_reason"]

    # 3. Relative strength < 20bp blocks weak leader even when SPY is bullish.
    r_low_rs = {**base, **execution_context(nvda_bars, spy_faster)}
    p_low_rs = plan(b, r_low_rs, price, now, now)
    assert not p_low_rs["executable"] and "相对SPY强弱" in p_low_rs["execution_reason"]

    # 4. Missing SPY data blocks entry cleanly.
    r_no_spy = {**base, **execution_context(nvda_bars, [])}
    p_no_spy = plan(b, r_no_spy, price, now, now)
    assert not p_no_spy["executable"] and "SPY" in p_no_spy["execution_reason"]

    # 5. Late SPY receipt delays quote_floor (zero lookahead on SPY bar).
    late_spy = list(spy_strong)
    late_receipt = now + timedelta(seconds=10)
    late_spy[-1] = replace(late_spy[-1], received_at=late_receipt)
    r_late_spy = {**base, **execution_context(nvda_bars, late_spy)}
    p_late = plan(b, r_late_spy, price, late_receipt + timedelta(seconds=2), now)
    assert not p_late["executable"] and "确认依据" in p_late["execution_reason"]
    p_after = plan(b, r_late_spy, price, late_receipt + timedelta(seconds=2), late_receipt + timedelta(seconds=1))
    assert p_after["executable"]

    # 6. Minimum 30bp initial risk gate blocks ultra-tight stops.
    tight = {**b, "invalidation": price - price * 0.001}
    p_tight = plan(tight, r_ok, price, now, now)
    assert not p_tight["executable"] and "初始风险幅度不足" in p_tight["execution_reason"]

    # 7. SPY itself is exempt from RS-vs-self while still requiring SPY VWAP alignment.
    spy_wide = _make_bars([500.0, 500.5, 501.0, 501.5, 502.0, 502.6], symbol="SPY.US", wick=Decimal("0.02"))
    spy_res = calculate("SPY.US", spy_wide, now)
    spy_b = next(x for x in spy_res["opportunities"]["branches"] if x["kind"] == "opening_breakout")
    spy_ctx = {**spy_res, **execution_context(spy_wide, spy_wide)}
    spy_price = spy_b["trigger"] + 0.6 * spy_b["atr"]
    p_spy_self = plan(spy_b, spy_ctx, spy_price, now, now, settings=StartPolicy(minimum_risk_return=0.0))
    assert p_spy_self["executable"]


@pytest.mark.parametrize("side", [1, -1])
def test_two_stage_structural_trailing_stop_ignores_pre_entry_bars(side):
    entry_at = NOW
    r = result(entry_at, side=side)
    # entry = 100 + side * 0.5, invalidation = 100 - side * 1.0 -> risk = 1.5
    entry_price = 100 + side * 0.5
    state, _ = transition({}, "NVDA.US", r, quote(entry_at, entry_price), entry_at)
    assert state["position"]["protection"] == pytest.approx(100 - side * 1.0)

    # Stage 1: +1.2R (= 1.8) moves protection to breakeven (entry_price).
    t1 = entry_at + timedelta(minutes=2)
    p1 = entry_price + side * 1.85
    state, events = transition(state, "NVDA.US", r, quote(t1, p1), t1)
    assert state["position"]["protection"] == pytest.approx(entry_price)
    assert state["position"]["protection_stage"] == "breakeven"
    assert any(e["kind"] == "hold" and "1.2R" in e["reason"] for e in events)

    # Stage 2: +2.5R (= 3.75) with pre-entry bar (must be ignored) and post-entry bars.
    t2 = entry_at + timedelta(minutes=5)
    p2 = entry_price + side * 3.75  # giveback_level = entry + side * (3.75 - 1.5) = entry + side * 2.25
    # Pre-entry bar has a favorable extreme that would illegally tighten if included;
    # post-entry bar has extreme at entry + side * 1.5.
    r_trail = deepcopy(r)
    r_trail["recent_bars"] = [
        dict(
            bar_time=(entry_at - timedelta(minutes=2)).isoformat(),
            close_at=(entry_at - timedelta(minutes=1)).isoformat(),
            high=entry_price + side * 3.0 if side == -1 else entry_price + 5.0,
            low=entry_price + side * 3.0 if side == 1 else entry_price - 5.0,
        ),
        dict(
            bar_time=(entry_at + timedelta(minutes=1)).isoformat(),
            close_at=(entry_at + timedelta(minutes=2)).isoformat(),
            high=entry_price + side * 1.5 if side == -1 else entry_price + 3.0,
            low=entry_price + side * 1.5 if side == 1 else entry_price - 3.0,
        ),
    ]
    state, events = transition(state, "NVDA.US", r_trail, quote(t2, p2), t2)
    # Wider of struct_level (entry + side*1.5) and giveback_level (entry + side*2.25) is entry + side*1.5!
    assert state["position"]["protection"] == pytest.approx(entry_price + side * 1.5)
    assert state["position"]["protection_stage"] == "trailing"
    assert any(e["kind"] == "hold" and "2.0R" in e["reason"] for e in events)

    # Pullback touching the structural trailing protection exits with trailing reason.
    t3 = t2 + timedelta(seconds=10)
    state, events = transition(state, "NVDA.US", r_trail, quote(t3, entry_price + side * 1.4), t3)
    assert not state["position"]
    exit_trade = next(e["trade"] for e in events if e["kind"] == "exit")
    assert "保护位" in exit_trade["exit_reason"]
    assert exit_trade["return_pct"] > 0


def test_cooldowns_daily_entry_cap_and_next_day_reset():
    def fresh_result(at, tag, side=1):
        r = result(at, side=side)
        r["opportunities"]["branches"][0].update(
            structure_id=f"s:{tag}",
            process_id=f"p:{tag}",
            started_at=at.isoformat(),
            structure_start=(at - timedelta(minutes=1)).isoformat(),
            structure_end=at.isoformat(),
        )
        return r

    # Trade 1: bullish entry, then stop out at a loss.
    t0 = NOW
    state, _ = transition({}, "NVDA.US", fresh_result(t0, "1", 1), quote(t0, 100.5), t0)
    assert state["daily_entry_count"] == 1
    t_stop = t0 + timedelta(minutes=1)
    state, events = transition(state, "NVDA.US", fresh_result(t_stop, "1", 1), quote(t_stop, 98.5), t_stop)
    assert not state["position"] and next(e["trade"] for e in events if e["kind"] == "exit")["return_pct"] < 0

    # 5 minutes later: both long and short blocked by 10-minute exit cooldown.
    t5 = t_stop + timedelta(minutes=5)
    state, _ = transition(state, "NVDA.US", fresh_result(t5, "2s", -1), quote(t5, 99.5), t5)
    assert not state["position"] and "10分钟冷却" in state["plans"][0]["execution_reason"]
    assert state["plans"][0]["opportunity_valid"]

    # 16 minutes after stop (past 15m prior box window and 10m exit cooldown):
    # same-side (long) still blocked by 20m stop cooldown, while opposite side (short) is allowed!
    t16 = t_stop + timedelta(minutes=16)
    state, _ = transition(state, "NVDA.US", fresh_result(t16, "2l", 1), quote(t16, 100.5), t16)
    assert not state["position"] and "20分钟冷却" in state["plans"][0]["execution_reason"]
    state, _ = transition(state, "NVDA.US", fresh_result(t16, "2s", -1), quote(t16, 99.5), t16)
    assert state["position"] and state["position"]["side"] == -1 and state["daily_entry_count"] == 2

    # Close trade 2 at a profit, wait 25 minutes -> 3rd entry blocked by max_daily_entries=2!
    t_win = t16 + timedelta(minutes=1)
    state, _ = transition(state, "NVDA.US", fresh_result(t_win, "2s", -1), quote(t_win, 97.5), t_win)
    # Trigger breakeven then exit at 99.5
    t_be_exit = t_win + timedelta(seconds=5)
    state, _ = transition(state, "NVDA.US", fresh_result(t_win, "2s", -1), quote(t_be_exit, 99.6), t_be_exit)
    assert not state["position"]
    t_third = t_win + timedelta(minutes=25)
    state, _ = transition(
        json.loads(json.dumps(state)), "NVDA.US", fresh_result(t_third, "3", 1), quote(t_third, 100.5), t_third
    )
    assert not state["position"] and "最大开仓次数上限" in state["plans"][0]["execution_reason"]
    assert state["plans"][0]["opportunity_valid"]

    # Next trading day resets daily cap and cooldowns.
    next_day = NOW + timedelta(days=1)
    state, _ = transition(state, "NVDA.US", fresh_result(next_day, "4", 1), quote(next_day, 100.5), next_day)
    assert state["position"] and state["daily_entry_count"] == 1


def test_legacy_v4_open_position_exits_cleanly_on_v4_target_and_cutoff():
    bounds = session_bounds("US", NOW.date())
    v4_cutoff = bounds[1] - timedelta(hours=2)
    legacy_state = {
        "symbol": "NVDA.US",
        "trading_date": NOW.date().isoformat(),
        "calculated_at": (NOW - timedelta(seconds=5)).isoformat(),
        "healthy": True,
        "position": {
            "id": "NVDA.US:legacy",
            "symbol": "NVDA.US",
            "trading_date": NOW.date().isoformat(),
            "side": 1,
            "kind": "pivot_breakout",
            "opportunity_id": "legacy:1",
            "process_id": "legacy:1",
            "version": "underlying_sim_v4",
            "entry_price": 100.0,
            "entry_at": (NOW - timedelta(minutes=5)).isoformat(),
            "entry_price_at": (NOW - timedelta(minutes=5)).isoformat(),
            "invalidation": 99.0,
            "protection": 99.0,
            "target": 102.0,
            "cutoff": v4_cutoff.isoformat(),
            "peak_gain": 0.0,
            "last_price": 100.5,
            "last_price_at": (NOW - timedelta(seconds=5)).isoformat(),
            "return_pct": 0.5,
        },
    }
    # Legacy V4 target still exits cleanly even though V5 disables pivot targets for new entries.
    s1, ev1 = transition(deepcopy(legacy_state), "NVDA.US", None, quote(NOW, 102.1), NOW)
    assert not s1["position"]
    assert next(e["trade"] for e in ev1 if e["kind"] == "exit")["exit_reason"] == "到达目标"

    # Legacy V4 14:00 cutoff still closes the open V4 position on schedule.
    at_v4_cutoff = v4_cutoff + timedelta(seconds=2)
    legacy_state["calculated_at"] = (v4_cutoff - timedelta(seconds=3)).isoformat()
    legacy_state["position"]["last_price_at"] = (v4_cutoff - timedelta(seconds=3)).isoformat()
    s2, ev2 = transition(deepcopy(legacy_state), "NVDA.US", None, quote(at_v4_cutoff, 100.6), at_v4_cutoff)
    assert not s2["position"]
    assert next(e["trade"] for e in ev2 if e["kind"] == "exit")["planned_exit_at"] == v4_cutoff.isoformat()

"""V6 big-wave low-frequency intraday strategy tests."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from finance_analysis.interfaces.api.v1.schemas.intraday_options import TrendResult
from finance_analysis.intraday_options.rules import ENTRY_VERSION, SIMULATION_VERSION, StartPolicy, policy
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import CONFIG, plan, transition
from finance_analysis.intraday_options.structure import execution_context, pool_rank_context
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


def _make_peer_pool(nvda_bars, side=1, nvda_rank=1, count=12):
    """Build causal peer pool of `count` stocks (including NVDA.US) where NVDA ranks `nvda_rank`."""
    peers = {"NVDA.US": nvda_bars}
    n = len(nvda_bars)
    nvda_ret = float(nvda_bars[-1].close) / float(nvda_bars[0].open) - 1.0
    for idx in range(count - 1):
        sym = f"PEER{idx:02d}.US"
        if idx < nvda_rank - 1:
            # Stronger than NVDA in direction `side`
            target_ret = nvda_ret + side * (0.008 + idx * 0.003)
        else:
            # Weaker than NVDA in direction `side`
            target_ret = nvda_ret - side * (0.004 + (idx + 1) * 0.002)
        vals = [100.0 + (100.0 * target_ret) * (i / max(1, n - 1)) for i in range(n)]
        peers[sym] = _make_bars(vals, symbol=sym, wick=Decimal("0.01"))
    return peers


def test_v6_policy_defaults_focus_on_low_frequency_big_wave_leaders(monkeypatch):
    for key in (
        "INTRADAY_OPENING_BREAKOUT",
        "INTRADAY_MIDDAY_WAVE_BREAKOUT",
        "INTRADAY_BOX_BREAKOUT",
        "INTRADAY_TREND_CONTINUATION",
        "INTRADAY_PIVOT_BREAKOUT",
        "INTRADAY_TREND_RECOVERY",
        "INTRADAY_USE_PIVOT_TARGET",
        "INTRADAY_OPENING_MIN_RANGE_PCT",
        "INTRADAY_MIDDAY_WINDOW_MINUTES",
        "INTRADAY_MIDDAY_MIN_WIDTH_PCT",
        "INTRADAY_MIDDAY_MAX_WIDTH_PCT",
        "INTRADAY_MIDDAY_MAX_EFFICIENCY",
        "INTRADAY_MIDDAY_START_MINUTES",
        "INTRADAY_MIDDAY_END_MINUTES",
        "INTRADAY_MIDDAY_REQUIRE_SESSION_EXTREME",
        "INTRADAY_MIN_TARGET_RETURN",
        "INTRADAY_MIN_REWARD_RISK",
        "INTRADAY_MIN_RISK_RETURN",
        "INTRADAY_MAX_RISK_RETURN",
        "INTRADAY_REQUIRE_VWAP",
        "INTRADAY_REQUIRE_SPY_ALIGNMENT",
        "INTRADAY_MIN_RELATIVE_STRENGTH",
        "INTRADAY_MIN_OPEN_MOVE",
        "INTRADAY_POOL_LEADER_TOP_K",
    ):
        monkeypatch.delenv(key, raising=False)
    policy.cache_clear()
    try:
        cfg = policy()
        assert cfg.opening_enabled is True
        assert cfg.midday_wave_enabled is True
        assert cfg.box_enabled is False
        assert cfg.continuation_enabled is False
        assert cfg.pivot_enabled is False
        assert cfg.recovery_enabled is False
        assert cfg.use_pivot_target is False
        assert cfg.opening_min_range_pct == pytest.approx(0.008)
        assert cfg.midday_window_minutes == 60
        assert cfg.midday_min_width_pct == pytest.approx(0.012)
        assert cfg.midday_max_width_pct == pytest.approx(0.050)
        assert cfg.midday_max_efficiency == pytest.approx(0.55)
        assert cfg.midday_start_minutes == 50
        assert cfg.midday_end_minutes == 150
        assert cfg.midday_require_session_extreme is True
        assert cfg.minimum_risk_return == pytest.approx(0.009)
        assert cfg.maximum_risk_return == pytest.approx(0.026)
        assert cfg.min_relative_strength == pytest.approx(0.010)
        assert cfg.min_open_move == pytest.approx(0.010)
        assert cfg.pool_leader_top_k == 2
        assert CONFIG.max_daily_entries == 1
        assert CONFIG.no_progress_minutes == 90
        assert CONFIG.no_progress_underwater_only is True
        assert CONFIG.breakeven_after_r == pytest.approx(1.5)
        assert CONFIG.trail_after_r == pytest.approx(2.5)
        assert CONFIG.trail_giveback_r == pytest.approx(1.2)
        assert CONFIG.trail_bars == 45
        assert CONFIG.entry_window_minutes == 150
        assert CONFIG.min_entry_before_close_minutes == 90
        assert ENTRY_VERSION == "intraday_entry_v6"
        assert SIMULATION_VERSION == "underlying_sim_v6"
    finally:
        policy.cache_clear()


@pytest.mark.parametrize("side", [1, -1])
def test_v6_opening_range_width_080pct_and_strong_bar_045atr(side):
    # Moderate opening range (~0.50% < 0.80%) is ignored in V6.
    narrow = _make_bars([100 + side * i * 0.12 for i in range(7)], wick=Decimal("0.001"))
    r_narrow = calculate("NVDA.US", narrow, narrow[-1].bar_time + timedelta(minutes=1, seconds=2))
    assert not any(b["kind"] == "opening_breakout" for b in r_narrow["opportunities"]["branches"])

    # Wide opening range (~0.88% >= 0.80%) with weak breakout bar waits for 2nd close.
    base = [100 + side * i * 0.22 for i in range(5)]  # range ~0.88%
    bars = _make_bars(base + [base[-1] + side * 0.08, base[-1] + side * 0.15], wick=Decimal("0.001"))
    bars[5] = replace(
        bars[5],
        high=bars[5].high + Decimal("0.30"),
        low=bars[5].low - Decimal("0.30"),
    )
    first_at = bars[5].bar_time + timedelta(minutes=1, seconds=2)
    r1 = calculate("NVDA.US", bars[:6], first_at)
    b1 = next(b for b in r1["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    assert b1["status"] == "forming" and b1["confirmed_at"] is None

    second_at = bars[6].bar_time + timedelta(minutes=1, seconds=2)
    r2 = calculate("NVDA.US", bars, second_at)
    b2 = next(b for b in r2["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    assert b2["status"] == "confirmed" and b2["confirmation_method"] == "two_closes"

    # Strong breakout bar (>= 0.45 ATR + body >= 60%) confirms immediately on first close.
    strong = _make_bars(base + [base[-1] + side * 0.22], wick=Decimal("0.001"))
    r_strong = calculate("NVDA.US", strong, strong[-1].bar_time + timedelta(minutes=1, seconds=2))
    b_strong = next(b for b in r_strong["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    assert b_strong["status"] == "confirmed" and b_strong["confirmation_method"] == "strong_break"


@pytest.mark.parametrize("side", [1, -1])
def test_v6_midday_wave_requires_60m_base_and_session_extreme_hod_lod(side):
    # 55-minute macro consolidation (~2.0% width) where breakout pushes to a NEW session HOD/LOD.
    coil = [100 + side * (1.0 * (1 if i % 6 in (1, 2, 3) else -1)) for i in range(55)]
    breakout = [100 + side * 1.45, 100 + side * 1.75]
    bars = _make_bars(coil + breakout, symbol="NVDA.US", wick=Decimal("0.02"))
    now = bars[-1].bar_time + timedelta(minutes=1, seconds=2)
    res = calculate("NVDA.US", bars, now)
    TrendResult.model_validate(res)
    midday = [b for b in res["opportunities"]["branches"] if b["kind"] == "midday_wave_breakout"]
    assert len(midday) == 1
    branch = midday[0]
    assert branch["status"] == "confirmed"
    assert branch["direction"] == ("bullish" if side == 1 else "bearish")

    # Inside-day coil: an early spike exceeds the coil's extreme by > 0.15%, so V6 rejects midday breakout!
    spiked = list(bars)
    if side == 1:
        spiked[1] = replace(spiked[1], high=Decimal("103.50"))
    else:
        spiked[1] = replace(spiked[1], low=Decimal("96.50"))
    res_inside = calculate("NVDA.US", spiked, now)
    assert not any(b["kind"] == "midday_wave_breakout" for b in res_inside["opportunities"]["branches"])

    # Rolling replay preserves exact frozen identity and trigger across subsequent minutes.
    ext_vals = coil + breakout + [100 + side * 1.85, 100 + side * 1.95]
    extended = _make_bars(ext_vals, symbol="NVDA.US", wick=Decimal("0.02"))
    res_later = calculate("NVDA.US", extended, extended[-1].bar_time + timedelta(minutes=1, seconds=2))
    later = next(b for b in res_later["opportunities"]["branches"] if b["structure_id"] == branch["structure_id"])
    for key in ("trigger", "invalidation", "atr", "started_at", "confirmed_at", "structure_start", "structure_end"):
        assert later[key] == branch[key]

    # Late revision inside the consolidation window cannot retroactively manufacture a historical break.
    late = list(bars)
    late[25] = replace(late[25], received_at=bars[-1].bar_time + timedelta(minutes=2))
    res_late = calculate("NVDA.US", late, bars[-1].bar_time + timedelta(minutes=2, seconds=5))
    assert not any(b["kind"] == "midday_wave_breakout" for b in res_late["opportunities"]["branches"])

    # Late revision on an early morning bar (before the 60m coil) also cannot retroactively qualify HOD/LOD.
    late_open = list(bars)
    late_open[0] = replace(late_open[0], received_at=bars[-1].bar_time + timedelta(minutes=2))
    res_late_open = calculate("NVDA.US", late_open, bars[-1].bar_time + timedelta(minutes=2, seconds=5))
    assert not any(b["kind"] == "midday_wave_breakout" for b in res_late_open["opportunities"]["branches"])


@pytest.mark.parametrize("side", [1, -1])
def test_v6_leader_rank_open_move_risk_window_and_spy_rs_gates(side):
    # Build NVDA strong big-wave opening breakout: 5m OR ~1.6% width (ATR ~0.44), bar 5 breaks out to ~2.2%.
    nvda_vals = [100 + side * x for x in (0.0, 0.40, 0.80, 1.20, 1.60, 2.25)]
    nvda_bars = _make_bars(nvda_vals, symbol="NVDA.US", wick=Decimal("0.02"))
    spy_ok = _make_bars(
        [500 + side * x for x in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)], symbol="SPY.US", wick=Decimal("0.02")
    )
    spy_fast = _make_bars(
        [500 + side * x for x in (0.0, 1.5, 3.0, 4.5, 6.0, 8.5)], symbol="SPY.US", wick=Decimal("0.02")
    )

    now = nvda_bars[-1].bar_time + timedelta(minutes=1, seconds=5)
    base = calculate("NVDA.US", nvda_bars, now)
    b = next(x for x in base["opportunities"]["branches"] if x["kind"] == "opening_breakout")
    assert b["status"] == "confirmed"
    # Live price inside [trigger, trigger + 2 ATR] with natural risk ~1.05% (in [0.9%, 2.6%] and <= 3.15 ATR).
    price = b["trigger"] + side * 1.4 * b["atr"]
    b_mid = b

    # 1. All V6 gates pass when NVDA is Rank #1 (or #2) in the 12-stock pool!
    peers_rank2 = _make_peer_pool(nvda_bars, side=side, nvda_rank=2, count=12)
    r_ok = {**base, **execution_context(nvda_bars, spy_ok, peer_bars=peers_rank2)}
    assert r_ok["pool_rank_context"]["long_rank" if side == 1 else "short_rank"] == 2
    p_ok = plan(b_mid, r_ok, price, now, now)
    assert p_ok["executable"] and p_ok["target"] is None and p_ok["target_source"] == "移动止损跟踪"

    # 2. Rank #3 is rejected by pool_leader_top_k=2.
    peers_rank3 = _make_peer_pool(nvda_bars, side=side, nvda_rank=3, count=12)
    r_rank3 = {**base, **execution_context(nvda_bars, spy_ok, peer_bars=peers_rank3)}
    p_rank3 = plan(b_mid, r_rank3, price, now, now)
    assert not p_rank3["executable"] and "横向强弱排名第3位" in p_rank3["execution_reason"]

    # 3. Insufficient peers (< 10) yields None pool_rank_context and cleanly blocks entry.
    small_pool = dict(list(peers_rank2.items())[:5])
    r_small = {**base, **execution_context(nvda_bars, spy_ok, peer_bars=small_pool)}
    assert r_small["pool_rank_context"] is None
    p_small = plan(b_mid, r_small, price, now, now)
    assert not p_small["executable"] and "横向强弱排名" in p_small["execution_reason"]

    # 4. Late peer receipt delays entry quote_floor (zero lookahead on cross-sectional rank!).
    late_peers = deepcopy(peers_rank2)
    late_receipt = now + timedelta(seconds=12)
    late_peers["PEER00.US"][-1] = replace(late_peers["PEER00.US"][-1], received_at=late_receipt)
    r_late_peer = {**base, **execution_context(nvda_bars, spy_ok, peer_bars=late_peers)}
    p_late = plan(b_mid, r_late_peer, price, late_receipt + timedelta(seconds=2), now)
    assert not p_late["executable"] and "确认依据" in p_late["execution_reason"]
    p_after = plan(b_mid, r_late_peer, price, late_receipt + timedelta(seconds=2), late_receipt + timedelta(seconds=1))
    assert p_after["executable"]

    # 5. Relative strength < 1.00% blocks weak breakout even if SPY aligns.
    r_low_rs = {**base, **execution_context(nvda_bars, spy_fast, peer_bars=peers_rank2)}
    p_low_rs = plan(b_mid, r_low_rs, price, now, now)
    assert not p_low_rs["executable"] and "相对SPY强弱不足1.00%" in p_low_rs["execution_reason"]

    # 6. Initial risk < 0.90% is blocked (filters narrow-range noise).
    b_tight = {**b, "invalidation": price - side * price * 0.006}
    p_tight = plan(b_tight, r_ok, price, now, now)
    assert not p_tight["executable"] and "初始风险幅度不足0.90%" in p_tight["execution_reason"]

    # 7. Initial risk > 2.60% is blocked (caps tail stop loss).
    price_wide = b["trigger"] + side * 0.9
    b_wide = {**b, "invalidation": price_wide - side * price_wide * 0.030, "atr": 1.5}
    p_wide = plan(b_wide, r_ok, price_wide, now, now)
    assert not p_wide["executable"] and "初始风险幅度超过2.60%" in p_wide["execution_reason"]

    # 8. Open move < 1.00% is blocked even if risk and SPY pass.
    r_small_move = deepcopy(r_ok)
    r_small_move["market_context"]["open_return"] = side * 0.006
    p_small_move = plan(b_mid, r_small_move, price, now, now)
    assert not p_small_move["executable"] and "日内相对开盘推进不足1.00%" in p_small_move["execution_reason"]

    # 9. Missing rank key yields missing-data reason (never formats "None").
    r_none_rank = deepcopy(r_ok)
    r_none_rank["pool_rank_context"]["long_rank"] = None
    r_none_rank["pool_rank_context"]["short_rank"] = None
    p_none_rank = plan(b_mid, r_none_rank, price, now, now)
    assert not p_none_rank["executable"] and "None" not in p_none_rank["execution_reason"]

    # 10. min_open_move alone still respects market_context evidence_at quote floor.
    open_only_cfg = StartPolicy(require_vwap=False, require_spy_alignment=False, pool_leader_top_k=0)
    r_late_mkt = deepcopy(r_ok)
    r_late_mkt["market_context"]["evidence_at"] = (now + timedelta(seconds=8)).isoformat()
    p_late_mkt = plan(b_mid, r_late_mkt, price, now + timedelta(seconds=10), now, settings=open_only_cfg)
    assert not p_late_mkt["executable"] and "确认依据" in p_late_mkt["execution_reason"]


def test_v6_policy_rejects_inverted_risk_bounds(monkeypatch):
    monkeypatch.setenv("INTRADAY_MIN_RISK_RETURN", "0.03")
    monkeypatch.setenv("INTRADAY_MAX_RISK_RETURN", "0.01")
    policy.cache_clear()
    try:
        with pytest.raises(ValueError, match="INTRADAY_MAX_RISK_RETURN"):
            policy()
    finally:
        policy.cache_clear()


def test_v6_midday_wave_stops_before_1200_ny_entry_cutoff():
    # Bar at elapsed_minutes == 150 (12:00 NY, closes at 12:01 NY) is after 12:00 entry cutoff -> ignored.
    coil = [100.0 + (1.0 if i % 6 in (1, 2, 3) else -1.0) for i in range(150)]
    bars = _make_bars(coil + [101.65], symbol="NVDA.US", wick=Decimal("0.02"))
    assert (bars[-1].bar_time - START) == timedelta(minutes=150)
    res = calculate("NVDA.US", bars, bars[-1].bar_time + timedelta(minutes=1, seconds=2))
    assert not any(b["kind"] == "midday_wave_breakout" for b in res["opportunities"]["branches"])


def test_scheduler_peer_snapshot_keeps_opening_and_recent_tail_only():
    from finance_analysis.intraday_options.scheduler import _peer_open_and_latest_bars

    yesterday = _make_bars([99.0, 99.5], symbol="AMD.US", start=START - timedelta(days=1))
    today = _make_bars([100.0 + 0.05 * i for i in range(30)], symbol="AMD.US", start=START)
    now = START + timedelta(minutes=30, seconds=5)
    snap = _peer_open_and_latest_bars([*yesterday, *today], START, now)
    times = [b.bar_time for b in snap]
    assert START in times
    assert all(t >= START for t in times)
    assert (START + timedelta(minutes=10)) not in times
    assert (START + timedelta(minutes=29)) in times


def test_pool_rank_context_works_when_symbol_omitted_from_peer_dict():
    nvda_bars = _make_bars([100.0, 100.4, 100.8, 101.2, 101.6, 102.0], symbol="NVDA.US")
    peers = _make_peer_pool(nvda_bars, side=1, nvda_rank=1, count=12)
    peers.pop("NVDA.US")
    day = nvda_bars[-1].bar_time.date()
    opening = session_bounds("US", day)[0]
    ctx = pool_rank_context("NVDA.US", nvda_bars, peers, opening, day)
    assert ctx is not None and ctx["long_rank"] == 1 and ctx["pool_size"] == 12


@pytest.mark.parametrize("side", [1, -1])
def test_v6_two_stage_45m_trailing_stop_and_90m_underwater_only_timeout(side):
    entry_at = NOW
    r = result(entry_at, side=side)
    # entry = 100 + side * 0.5, invalidation = 100 - side * 1.0 -> risk = 1.5 (~1.5% in [0.9%, 2.6%])
    entry_price = 100 + side * 0.5
    state, _ = transition({}, "NVDA.US", r, quote(entry_at, entry_price), entry_at)
    assert state["position"]["protection"] == pytest.approx(100 - side * 1.0)

    # At +1.2R (old V5 threshold): V6 does NOT move to breakeven yet (needs 1.5R)!
    t0 = entry_at + timedelta(minutes=2)
    state, events = transition(state, "NVDA.US", r, quote(t0, entry_price + side * 1.85), t0)
    assert state["position"]["protection"] == pytest.approx(100 - side * 1.0)
    assert not events

    # Stage 1: +1.5R (= 2.25) moves protection to breakeven.
    t1 = entry_at + timedelta(minutes=5)
    state, events = transition(state, "NVDA.US", r, quote(t1, entry_price + side * 2.30), t1)
    assert state["position"]["protection"] == pytest.approx(entry_price)
    assert state["position"]["protection_stage"] == "breakeven"
    assert any(e["kind"] == "hold" and "1.5R" in e["reason"] for e in events)

    # Stage 2: +2.5R (= 3.75) activates 45-bar structural trail (wider of 45m extreme and peak - 1.2R).
    # Build 50 post-entry bars so we also verify recent_bars window holds > 20 bars!
    t2 = entry_at + timedelta(minutes=52)
    p2 = entry_price + side * 3.80  # giveback_level = entry + side * (3.80 - 1.80) = entry + side * 2.00
    r_trail = deepcopy(r)
    r_trail["recent_bars"] = [
        # Pre-entry bar (must be ignored even though extreme is deep)
        dict(
            bar_time=(entry_at - timedelta(minutes=2)).isoformat(),
            close_at=(entry_at - timedelta(minutes=1)).isoformat(),
            high=entry_price + side * 3.2 if side == -1 else entry_price + 5.0,
            low=entry_price + side * 3.2 if side == 1 else entry_price - 5.0,
        ),
        # Post-entry bar #1 (44 minutes before t2 -> INSIDE 45m window, extreme at entry + side * 1.2)
        dict(
            bar_time=(entry_at + timedelta(minutes=7)).isoformat(),
            close_at=(entry_at + timedelta(minutes=8)).isoformat(),
            high=entry_price + side * 1.2 if side == -1 else entry_price + 4.0,
            low=entry_price + side * 1.2 if side == 1 else entry_price - 4.0,
        ),
    ] + [
        dict(
            bar_time=(entry_at + timedelta(minutes=9 + i)).isoformat(),
            close_at=(entry_at + timedelta(minutes=10 + i)).isoformat(),
            high=entry_price + side * 2.5 if side == -1 else entry_price + 4.0,
            low=entry_price + side * 2.5 if side == 1 else entry_price - 4.0,
        )
        for i in range(42)
    ]
    state, events = transition(state, "NVDA.US", r_trail, quote(t2, p2), t2)
    # Wider of struct_level (entry + side*1.2) and giveback_level (entry + side*2.0) is entry + side*1.2!
    assert state["position"]["protection"] == pytest.approx(entry_price + side * 1.2)
    assert state["position"]["protection_stage"] == "trailing"
    assert any(e["kind"] == "hold" and "2.5R" in e["reason"] and "45分钟" in e["reason"] for e in events)

    # Pullback touching the trailing protection exits cleanly with positive return.
    t3 = t2 + timedelta(seconds=10)
    state, events = transition(state, "NVDA.US", r_trail, quote(t3, entry_price + side * 1.1), t3)
    assert not state["position"]
    exit_trade = next(e["trade"] for e in events if e["kind"] == "exit")
    assert "保护位" in exit_trade["exit_reason"] and exit_trade["return_pct"] > 0

    # 90m underwater-only timeout: stays open at 95m if profitable, exits at 96m when underwater.
    state2, _ = transition({}, "NVDA.US", r, quote(entry_at, entry_price), entry_at)
    t95 = entry_at + timedelta(minutes=95)
    state2, ev95 = transition(state2, "NVDA.US", r, quote(t95, entry_price + side * 0.10), t95)
    assert state2["position"] and not ev95
    t96 = entry_at + timedelta(minutes=96)
    state2, ev96 = transition(state2, "NVDA.US", r, quote(t96, entry_price - side * 0.05), t96)
    assert not state2["position"]
    assert "90分钟水下滞涨退出" == next(e["trade"] for e in ev96 if e["kind"] == "exit")["exit_reason"]


def test_v6_max_one_entry_per_symbol_per_day_and_next_day_reset():
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

    # Trade 1 at 10:00 NY (15:00 UTC), then closes at stop.
    t0 = NOW - timedelta(minutes=60)
    state, _ = transition({}, "NVDA.US", fresh_result(t0, "1", 1), quote(t0, 100.5), t0)
    assert state["daily_entry_count"] == 1
    t_stop = t0 + timedelta(minutes=2)
    state, events = transition(state, "NVDA.US", fresh_result(t_stop, "1", 1), quote(t_stop, 98.5), t_stop)
    assert not state["position"] and next(e["trade"] for e in events if e["kind"] == "exit")["return_pct"] < 0

    # Even 70 minutes later (past cooldown), 2nd entry is blocked by V6 max_daily_entries=1!
    t_later = t_stop + timedelta(minutes=70)
    state, _ = transition(
        json.loads(json.dumps(state)), "NVDA.US", fresh_result(t_later, "2", -1), quote(t_later, 99.5), t_later
    )
    assert not state["position"] and "最大开仓次数上限（1笔）" in state["plans"][0]["execution_reason"]
    assert state["plans"][0]["opportunity_valid"]

    # Next trading day resets daily entry count and cooldowns.
    next_day = t0 + timedelta(days=1)
    state, _ = transition(state, "NVDA.US", fresh_result(next_day, "3", 1), quote(next_day, 100.5), next_day)
    assert state["position"] and state["daily_entry_count"] == 1


def test_legacy_v4_and_v5_open_positions_exit_cleanly():
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
    s1, ev1 = transition(deepcopy(legacy_state), "NVDA.US", None, quote(NOW, 102.1), NOW)
    assert not s1["position"]
    assert next(e["trade"] for e in ev1 if e["kind"] == "exit")["exit_reason"] == "到达目标"

    at_v4_cutoff = v4_cutoff + timedelta(seconds=2)
    legacy_state["calculated_at"] = (v4_cutoff - timedelta(seconds=3)).isoformat()
    legacy_state["position"]["last_price_at"] = (v4_cutoff - timedelta(seconds=3)).isoformat()
    s2, ev2 = transition(deepcopy(legacy_state), "NVDA.US", None, quote(at_v4_cutoff, 100.6), at_v4_cutoff)
    assert not s2["position"]
    assert next(e["trade"] for e in ev2 if e["kind"] == "exit")["planned_exit_at"] == v4_cutoff.isoformat()

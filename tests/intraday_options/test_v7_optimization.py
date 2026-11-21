"""V7 Clean Opening Drive Leader (win-rate & per-trade return) strategy tests."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from finance_analysis.interfaces.api.v1.schemas.intraday_options import TrendResult
from finance_analysis.intraday_options.config import VERSION as CACHE_VERSION
from finance_analysis.intraday_options.rules import ENTRY_VERSION, SIMULATION_VERSION, StartPolicy, policy
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import CONFIG, plan, transition
from finance_analysis.intraday_options.structure import execution_context
from tests.intraday_options.test_scoring import START, candles
from tests.intraday_options.test_simulation import quote


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


def _make_peer_pool(nvda_bars, side=1, nvda_rank=1, breadth_ratio=0.75, count=12):
    """Build causal peer pool with exact NVDA rank and directional breadth."""
    peers = {"NVDA.US": nvda_bars}
    n = len(nvda_bars)
    nvda_ret = float(nvda_bars[-1].close) / float(nvda_bars[0].open) - 1.0
    n_same = max(nvda_rank, int(round(breadth_ratio * count)))
    for idx in range(count - 1):
        sym = f"PEER{idx:02d}.US"
        if idx < nvda_rank - 1:
            target_ret = nvda_ret + side * (0.008 + idx * 0.003)
        elif idx < n_same - 1:
            target_ret = side * max(0.003, abs(nvda_ret) - 0.006 - idx * 0.001)
        else:
            target_ret = -side * (0.004 + idx * 0.001)
        vals = [100.0 + (100.0 * target_ret) * (i / max(1, n - 1)) for i in range(n)]
        peers[sym] = _make_bars(vals, symbol=sym, start=nvda_bars[0].bar_time, wick=Decimal("0.01"))
    return peers


def test_v7_policy_defaults_and_validation(monkeypatch):
    env_keys = (
        "INTRADAY_OPENING_BREAKOUT",
        "INTRADAY_OPENING_MINUTES",
        "INTRADAY_OPENING_MIN_RANGE_PCT",
        "INTRADAY_OPENING_MIN_ELAPSED_MINUTES",
        "INTRADAY_OPENING_END_MINUTES",
        "INTRADAY_OPENING_MIN_EFFICIENCY",
        "INTRADAY_OPENING_REQUIRE_DIRECTIONAL_BAR",
        "INTRADAY_ENTRY_WINDOW_MINUTES",
        "INTRADAY_MIDDAY_WAVE_BREAKOUT",
        "INTRADAY_BOX_BREAKOUT",
        "INTRADAY_TREND_CONTINUATION",
        "INTRADAY_PIVOT_BREAKOUT",
        "INTRADAY_TREND_RECOVERY",
        "INTRADAY_USE_PIVOT_TARGET",
        "INTRADAY_STOP_LOSS_PCT",
        "INTRADAY_TAKE_PROFIT_PCT",
        "INTRADAY_PROFIT_LOCK_TRIGGER_PCT",
        "INTRADAY_PROFIT_LOCK_LEVEL_PCT",
        "INTRADAY_MIN_TARGET_RETURN",
        "INTRADAY_MIN_REWARD_RISK",
        "INTRADAY_MIN_RISK_RETURN",
        "INTRADAY_MAX_RISK_RETURN",
        "INTRADAY_REQUIRE_VWAP",
        "INTRADAY_REQUIRE_SPY_ALIGNMENT",
        "INTRADAY_MIN_RELATIVE_STRENGTH",
        "INTRADAY_MIN_OPEN_MOVE",
        "INTRADAY_MIN_SPY_OPEN_MOVE",
        "INTRADAY_MIN_POOL_BREADTH",
        "INTRADAY_POOL_LEADER_TOP_K",
    )
    for k in env_keys:
        monkeypatch.delenv(k, raising=False)
    policy.cache_clear()
    try:
        cfg = policy()
        assert CACHE_VERSION == "intraday_options_v17"
        assert ENTRY_VERSION == "intraday_entry_v7"
        assert SIMULATION_VERSION == "underlying_sim_v7"
        assert cfg.opening_enabled is True
        assert cfg.midday_wave_enabled is False
        assert cfg.box_enabled is False
        assert cfg.continuation_enabled is False
        assert cfg.pivot_enabled is False
        assert cfg.recovery_enabled is False
        assert cfg.opening_minutes == 5
        assert cfg.opening_min_range_pct == pytest.approx(0.008)
        assert cfg.opening_min_elapsed_minutes == 8
        assert cfg.opening_end_minutes == 30
        assert cfg.opening_min_efficiency == pytest.approx(0.55)
        assert cfg.opening_require_directional_bar is True
        assert cfg.entry_window_minutes == 30
        assert cfg.stop_loss_pct == pytest.approx(0.025)
        assert cfg.take_profit_pct == pytest.approx(0.035)
        assert cfg.profit_lock_trigger_pct == pytest.approx(0.020)
        assert cfg.profit_lock_level_pct == pytest.approx(0.002)
        assert cfg.min_open_move == pytest.approx(0.020)
        assert cfg.min_relative_strength == pytest.approx(0.015)
        assert cfg.min_spy_open_move == pytest.approx(0.0015)
        assert cfg.min_pool_breadth == pytest.approx(0.68)
        assert cfg.pool_leader_top_k == 2
        assert CONFIG.entry_window_minutes == 30
        assert CONFIG.max_daily_entries == 1
    finally:
        policy.cache_clear()


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"INTRADAY_OPENING_MIN_EFFICIENCY": "1.2"}, "EFFICIENCY"),
        ({"INTRADAY_MIN_POOL_BREADTH": "1.1"}, "BREADTH"),
        ({"INTRADAY_OPENING_MIN_ELAPSED_MINUTES": "20", "INTRADAY_OPENING_END_MINUTES": "15"}, "END_MINUTES"),
        ({"INTRADAY_PROFIT_LOCK_TRIGGER_PCT": "0.02", "INTRADAY_PROFIT_LOCK_LEVEL_PCT": "0.025"}, "LOCK_LEVEL"),
        ({"INTRADAY_TAKE_PROFIT_PCT": "0.02", "INTRADAY_PROFIT_LOCK_TRIGGER_PCT": "0.025"}, "LOCK_TRIGGER"),
    ],
)
def test_v7_policy_rejects_invalid_env_combinations(monkeypatch, overrides, match):
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    policy.cache_clear()
    try:
        with pytest.raises(ValueError, match=match):
            policy()
    finally:
        policy.cache_clear()


@pytest.mark.parametrize("side", [1, -1])
def test_v7_clean_opening_drive_gates_and_rolling_rank_admission(side):
    # Clean 8-bar drive: 5m OR ~1.4% (>= 0.8%), bar 7 (closes 09:38 NY) reaches +2.6% with eff == 1.0.
    vals8 = [100.0 + side * x for x in (0.0, 0.35, 0.70, 1.05, 1.40, 1.80, 2.20, 2.60)]
    nvda8 = _make_bars(vals8, symbol="NVDA.US", wick=Decimal("0.01"))
    spy_ok = _make_bars([500.0 + side * x for x in (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05)], symbol="SPY.US")
    spy_flat = _make_bars([500.0 + side * 0.05 * i for i in range(8)], symbol="SPY.US")

    # 1. Before minute 8 (only 7 bars, 09:37 NY): V7 waits until 09:38 NY.
    t7 = nvda8[6].bar_time + timedelta(minutes=1, seconds=3)
    r7 = calculate("NVDA.US", nvda8[:7], t7)
    assert not any(b["kind"] == "opening_breakout" for b in r7["opportunities"]["branches"])

    # 2. Choppy path (eff < 0.55) at minute 8 is rejected even with +2.6% move.
    choppy_vals = [100.0 + side * x for x in (0.0, 1.5, 0.1, 1.6, 0.2, 1.8, 0.5, 2.6)]
    choppy = _make_bars(choppy_vals, symbol="NVDA.US", wick=Decimal("0.01"))
    t8 = nvda8[-1].bar_time + timedelta(minutes=1, seconds=3)
    r_chop = calculate("NVDA.US", choppy, t8)
    assert not any(b["kind"] == "opening_breakout" for b in r_chop["opportunities"]["branches"])

    # 3. Counter-directional closing bar (red bar for long / green for short) is rejected.
    red_vals = [100.0 + side * x for x in (0.0, 0.40, 0.80, 1.20, 1.60, 2.10, 2.80, 2.60)]
    red_bars = _make_bars(red_vals, symbol="NVDA.US", wick=Decimal("0.01"))
    red_branches = calculate("NVDA.US", red_bars, t8)["opportunities"]["branches"]
    assert not any(b["kind"] == "opening_breakout" for b in red_branches)

    # 4. At minute 8 (09:38 NY), clean drive confirms and passes Pydantic TrendResult validation!
    base8 = calculate("NVDA.US", nvda8, t8)
    TrendResult.model_validate(base8)
    b8 = next(x for x in base8["opportunities"]["branches"] if x["kind"] == "opening_breakout")
    assert b8["status"] == "confirmed" and b8["opening_drive"] is True
    assert b8["confirmation_method"] == "level_close"
    price8 = float(nvda8[-1].close) + side * 0.05

    # 5. SPY flat (+0.01% < 0.15%) AND weak breadth (50% < 68%) -> blocked by macro resonance gate!
    peers_low_br = _make_peer_pool(nvda8, side=side, nvda_rank=1, breadth_ratio=0.50, count=12)
    r_weak_macro = {**base8, **execution_context(nvda8, spy_flat, peer_bars=peers_low_br)}
    p_weak = plan(b8, r_weak_macro, price8, t8, t8)
    assert not p_weak["executable"] and "大盘共振不足" in p_weak["execution_reason"]

    # 6. SPY flat (+0.01%) BUT strong breadth (75% >= 68%) -> PASSES via breadth confirmation!
    peers_hi_br = _make_peer_pool(nvda8, side=side, nvda_rank=1, breadth_ratio=0.75, count=12)
    r_br_ok = {**base8, **execution_context(nvda8, spy_flat, peer_bars=peers_hi_br)}
    assert r_br_ok["pool_rank_context"]["breadth_up" if side == 1 else "breadth_down"] >= 0.68
    p_br_ok = plan(b8, r_br_ok, price8, t8, t8)
    assert p_br_ok["executable"]
    assert p_br_ok["invalidation"] == pytest.approx(price8 * (1.0 - side * 0.025))
    assert p_br_ok["target"] == pytest.approx(price8 * (1.0 + side * 0.035))
    assert "V7波段止盈" in p_br_ok["target_source"]

    # 7. Rolling rank admission: Rank #3 at 09:38 blocks entry WITHOUT consuming process; Rank #2 at 09:39 enters!
    peers_r3 = _make_peer_pool(nvda8, side=side, nvda_rank=3, breadth_ratio=0.75, count=12)
    r_r3 = {**base8, **execution_context(nvda8, spy_ok, peer_bars=peers_r3)}
    state, ev8 = transition({}, "NVDA.US", r_r3, quote(t8, price8), t8)
    assert not state.get("position") and not any(e["kind"] == "entry" for e in ev8)

    vals9 = [*vals8, 100.0 + side * 3.05]
    nvda9 = _make_bars(vals9, symbol="NVDA.US", wick=Decimal("0.01"))
    spy9 = _make_bars(
        [500.0 + side * x for x in (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05, 1.20)], symbol="SPY.US"
    )
    t9 = nvda9[-1].bar_time + timedelta(minutes=1, seconds=3)
    base9 = calculate("NVDA.US", nvda9, t9)
    peers_r2 = _make_peer_pool(nvda9, side=side, nvda_rank=2, breadth_ratio=0.75, count=12)
    r_r2 = {**base9, **execution_context(nvda9, spy9, peer_bars=peers_r2)}
    price9 = float(nvda9[-1].close) + side * 0.05
    state, ev9 = transition(json.loads(json.dumps(state)), "NVDA.US", r_r2, quote(t9, price9), t9)
    assert state["position"] and state["position"]["exit_policy"] == "v7_fixed_wave"
    assert state["position"]["invalidation"] == pytest.approx(price9 * (1.0 - side * 0.025))
    assert state["position"]["target"] == pytest.approx(price9 * (1.0 + side * 0.035))
    assert any(e["kind"] == "entry" for e in ev9)
    # Rolling opening_drive shares one process_id -> second minute must not spam duplicate confirmed events.
    assert any(e["kind"] == "confirmed" for e in ev8)
    assert not any(e["kind"] == "confirmed" for e in ev9)


@pytest.mark.parametrize("side", [1, -1])
def test_v7_fixed_wave_exits_stop_profit_lock_tp_and_no_90m_underwater_cut(side):
    vals8 = [100.0 + side * x for x in (0.0, 0.35, 0.70, 1.05, 1.40, 1.80, 2.20, 2.60)]
    nvda8 = _make_bars(vals8, symbol="NVDA.US", wick=Decimal("0.01"))
    spy8 = _make_bars([500.0 + side * x for x in (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05)], symbol="SPY.US")
    peers = _make_peer_pool(nvda8, side=side, nvda_rank=1, breadth_ratio=0.75, count=12)
    t8 = nvda8[-1].bar_time + timedelta(minutes=1, seconds=3)
    r8 = {**calculate("NVDA.US", nvda8, t8), **execution_context(nvda8, spy8, peer_bars=peers)}
    ep = 100.0 + side * 2.65

    # Scenario A: +2.0% floating gain promotes protection to +0.20%, then reversal exits at profit-lock!
    s_lock, _ = transition({}, "NVDA.US", r8, quote(t8, ep), t8)
    assert s_lock["position"]["protection"] == pytest.approx(ep * (1.0 - side * 0.025))
    t_95m = t8 + timedelta(minutes=95)
    # V7 does NOT exit underwater at 95m (unlike V6's 90m underwater cut)!
    s_lock, ev_95 = transition(s_lock, "NVDA.US", None, quote(t_95m, ep * (1.0 - side * 0.008)), t_95m)
    assert s_lock["position"] and not ev_95
    # Rally to +2.1% triggers BE20_Lock20 (+0.20% lock).
    t_rally = t_95m + timedelta(minutes=10)
    s_lock, ev_rally = transition(s_lock, "NVDA.US", None, quote(t_rally, ep * (1.0 + side * 0.021)), t_rally)
    assert s_lock["position"]["protection"] == pytest.approx(ep * (1.0 + side * 0.002))
    assert s_lock["position"]["protection_stage"] == "profit_lock"
    assert any(e["kind"] == "hold" and "+0.20%锁盈" in e["reason"] for e in ev_rally)
    # Reversal touching +0.15% exits with profit-lock reason and positive return.
    t_rev = t_rally + timedelta(minutes=5)
    s_lock, ev_rev = transition(s_lock, "NVDA.US", None, quote(t_rev, ep * (1.0 + side * 0.0015)), t_rev)
    assert not s_lock["position"]
    tr_lock = next(e["trade"] for e in ev_rev if e["kind"] == "exit")
    assert tr_lock["exit_reason"] == "保本锁盈保护触及" and tr_lock["return_pct"] > 0

    # Scenario B: Direct +3.5% hit exits cleanly at wave take-profit target.
    s_tp, _ = transition({}, "NVDA.US", r8, quote(t8, ep), t8)
    t_tp = t8 + timedelta(minutes=30)
    s_tp, ev_tp = transition(s_tp, "NVDA.US", None, quote(t_tp, ep * (1.0 + side * 0.036)), t_tp)
    assert not s_tp["position"]
    tr_tp = next(e["trade"] for e in ev_tp if e["kind"] == "exit")
    assert tr_tp["exit_reason"] == "到达波段止盈目标" and tr_tp["return_pct"] >= 3.5

    # Scenario C: -2.5% hit exits cleanly at macro stop loss.
    s_sl, _ = transition({}, "NVDA.US", r8, quote(t8, ep), t8)
    t_sl = t8 + timedelta(minutes=15)
    s_sl, ev_sl = transition(s_sl, "NVDA.US", None, quote(t_sl, ep * (1.0 - side * 0.026)), t_sl)
    assert not s_sl["position"]
    tr_sl = next(e["trade"] for e in ev_sl if e["kind"] == "exit")
    assert tr_sl["exit_reason"] == "宏观止损触及" and tr_sl["return_pct"] <= -2.5

    # Scenario D: Disabling profit lock (profit_lock_trigger_pct=0) matches pure SL25/TP35.
    no_lock_cfg = StartPolicy(profit_lock_trigger_pct=0.0, profit_lock_level_pct=0.0)
    s_pure, _ = transition({}, "NVDA.US", r8, quote(t8, ep), t8, settings=no_lock_cfg)
    s_pure, ev_p1 = transition(
        s_pure, "NVDA.US", None, quote(t_rally, ep * (1.0 + side * 0.022)), t_rally, settings=no_lock_cfg
    )
    assert s_pure["position"]["protection"] == pytest.approx(ep * (1.0 - side * 0.025)) and not ev_p1


def test_v7_preserves_legacy_v6_open_position_exit_path():
    # A V6 open position (without exit_policy='v7_fixed_wave') still follows V6's 1.5R breakeven & 90m underwater rule.
    entry_at = START + timedelta(minutes=10)
    legacy_v6 = {
        "symbol": "NVDA.US",
        "trading_date": entry_at.date().isoformat(),
        "calculated_at": (entry_at - timedelta(seconds=5)).isoformat(),
        "healthy": True,
        "position": {
            "id": "NVDA.US:v6_legacy",
            "symbol": "NVDA.US",
            "trading_date": entry_at.date().isoformat(),
            "side": 1,
            "kind": "opening_breakout",
            "opportunity_id": "v6:1",
            "process_id": "v6:1",
            "version": "underlying_sim_v6",
            "entry_price": 100.0,
            "entry_at": entry_at.isoformat(),
            "entry_price_at": entry_at.isoformat(),
            "invalidation": 99.0,
            "protection": 99.0,
            "target": None,
            "cutoff": (START + timedelta(minutes=380)).isoformat(),
            "peak_gain": 0.0,
            "last_price": 100.0,
            "last_price_at": entry_at.isoformat(),
            "return_pct": 0.0,
        },
    }
    # At +1.6% (+1.6R), V6 moves to breakeven (100.0) even though V7 would wait for +2.0%.
    t1 = entry_at + timedelta(minutes=5)
    s1, ev1 = transition(deepcopy(legacy_v6), "NVDA.US", None, quote(t1, 101.6), t1)
    assert s1["position"]["protection"] == pytest.approx(100.0)
    assert any(e["kind"] == "hold" and "1.5R" in e["reason"] for e in ev1)


def test_v7_late_session_bar_revision_advances_quote_floor_and_stale_macro_fails_closed():
    vals8 = [100.0 + x for x in (0.0, 0.35, 0.70, 1.05, 1.40, 1.80, 2.20, 2.60)]
    nvda8 = _make_bars(vals8, symbol="NVDA.US", wick=Decimal("0.01"))
    t8 = nvda8[-1].bar_time + timedelta(minutes=1, seconds=3)
    late_rev = t8 + timedelta(seconds=12)
    # Bar 3 revised late -> V7 opening drive quote floor must wait until after late_rev!
    nvda_rev = [*nvda8[:3], replace(nvda8[3], received_at=late_rev), *nvda8[4:]]
    spy8 = _make_bars([500.0 + x for x in (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05)], symbol="SPY.US")
    peers = _make_peer_pool(nvda_rev, side=1, nvda_rank=1, breadth_ratio=0.75, count=12)
    now_after = late_rev + timedelta(seconds=2)
    r_rev = {**calculate("NVDA.US", nvda_rev, now_after), **execution_context(nvda_rev, spy8, peer_bars=peers)}
    b = next(x for x in r_rev["opportunities"]["branches"] if x["kind"] == "opening_breakout")
    price = 102.65
    p_early = plan(b, r_rev, price, now_after, t8)
    assert not p_early["executable"] and "确认依据" in p_early["execution_reason"]
    p_ok = plan(b, r_rev, price, now_after, late_rev + timedelta(seconds=1))
    assert p_ok["executable"]

    # Stale pool_rank_context (>120s behind) cannot satisfy breadth resonance even if pool_leader_top_k=0.
    breadth_only_cfg = StartPolicy(require_spy_alignment=False, pool_leader_top_k=0, min_spy_open_move=0.0)
    r_stale = deepcopy(r_rev)
    r_stale["pool_rank_context"]["as_of"] = (nvda8[0].bar_time - timedelta(minutes=5)).isoformat()
    p_stale = plan(b, r_stale, price, now_after, late_rev + timedelta(seconds=1), settings=breadth_only_cfg)
    assert not p_stale["executable"] and "大盘共振不足" in p_stale["execution_reason"]

    # Bar closing at 10:00 NY (30th minute) does NOT emit an unexecutable dead opening-drive branch.
    vals30 = [100.0 + 0.12 * i for i in range(30)]
    nvda30 = _make_bars(vals30, symbol="NVDA.US", wick=Decimal("0.01"))
    t30 = nvda30[-1].bar_time + timedelta(minutes=1, seconds=3)
    r30 = calculate("NVDA.US", nvda30, t30)
    assert not any(x["kind"] == "opening_breakout" for x in r30["opportunities"]["branches"])


def test_v7_ranked_opportunity_matches_fixed_wave_plan_and_legacy_two_close_threshold():
    from finance_analysis.intraday_options.runtime import ranked_opportunity

    vals8 = [100.0 + x for x in (0.0, 0.35, 0.70, 1.05, 1.40, 1.80, 2.20, 2.60)]
    nvda8 = _make_bars(vals8, symbol="NVDA.US", wick=Decimal("0.01"))
    spy8 = _make_bars([500.0 + x for x in (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05)], symbol="SPY.US")
    peers = _make_peer_pool(nvda8, side=1, nvda_rank=1, breadth_ratio=0.75, count=12)
    t8 = nvda8[-1].bar_time + timedelta(minutes=1, seconds=3)
    r8 = {**calculate("NVDA.US", nvda8, t8), **execution_context(nvda8, spy8, peer_bars=peers)}
    q8 = quote(t8, 102.65)
    sim_state, _ = transition({}, "NVDA.US", r8, q8, t8)
    ranked = ranked_opportunity(r8, sim_state, t8, q8)
    assert ranked is not None and ranked["kind"] == "opening_breakout"
    assert ranked["invalidation"] == pytest.approx(102.65 * 0.975)

    # Legacy non-opening-drive opening_breakout still requires > 0.20 ATR on both closes for two_closes.
    legacy_cfg = StartPolicy(
        opening_min_efficiency=0.0,
        opening_min_elapsed_minutes=5,
        opening_require_directional_bar=False,
        opening_min_range_pct=0.0,
        strong_break_atr=10.0,
    )
    # 5m OR high=101.62, ATR~0.44 -> 0.20*ATR~0.088. Bar 5 closes +0.18 (>0.20 ATR), bar 6 closes +0.02 (<0.20 ATR).
    legacy_bars = _make_bars(
        [100.0, 100.4, 100.8, 101.2, 101.6, 101.80, 101.64], symbol="NVDA.US", wick=Decimal("0.02")
    )
    t_leg = legacy_bars[-1].bar_time + timedelta(minutes=1, seconds=2)
    r_leg = calculate("NVDA.US", legacy_bars, t_leg, settings=legacy_cfg)
    b_leg = next(x for x in r_leg["opportunities"]["branches"] if x["kind"] == "opening_breakout")
    assert b_leg["status"] == "forming" and b_leg["confirmed_at"] is None

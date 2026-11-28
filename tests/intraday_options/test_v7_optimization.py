"""V7 Clean Opening Drive Leader compatibility & regression tests."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from finance_analysis.intraday_options.config import VERSION as CACHE_VERSION
from finance_analysis.intraday_options.rules import ENTRY_VERSION, SIMULATION_VERSION, StartPolicy, policy
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import CONFIG, plan, transition
from finance_analysis.intraday_options.structure import execution_context
from tests.intraday_options.historical import historical_signal
from tests.intraday_options.test_scoring import START, candles
from tests.intraday_options.test_simulation import quote


V7_POLICY = StartPolicy(
    opening_enabled=True,
    midday_wave_enabled=False,
    box_enabled=False,
    continuation_enabled=False,
    pivot_enabled=False,
    recovery_enabled=False,
    opening_minutes=5,
    opening_min_range_pct=0.008,
    opening_min_elapsed_minutes=8,
    opening_end_minutes=30,
    opening_min_efficiency=0.55,
    opening_require_directional_bar=True,
    entry_window_minutes=30,
    use_pivot_target=False,
    atr_scaled_exits=False,
    stop_loss_pct=0.025,
    take_profit_pct=0.035,
    profit_lock_trigger_pct=0.020,
    profit_lock_level_pct=0.002,
    min_gap_directional=None,
    min_open_move=0.020,
    min_relative_strength=0.015,
    min_spy_open_move=0.0015,
    min_pool_breadth=0.68,
    pool_leader_top_k=2,
)


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


def test_v7_policy_compatibility_flags_and_validation(monkeypatch):
    for k, v in (
        ("INTRADAY_OPENING_MIN_ELAPSED_MINUTES", "8"),
        ("INTRADAY_OPENING_END_MINUTES", "30"),
        ("INTRADAY_OPENING_MIN_EFFICIENCY", "0.55"),
        ("INTRADAY_ENTRY_WINDOW_MINUTES", "30"),
        ("INTRADAY_ATR_SCALED_EXITS", "false"),
        ("INTRADAY_STOP_LOSS_PCT", "0.025"),
        ("INTRADAY_TAKE_PROFIT_PCT", "0.035"),
        ("INTRADAY_PROFIT_LOCK_TRIGGER_PCT", "0.020"),
        ("INTRADAY_PROFIT_LOCK_LEVEL_PCT", "0.002"),
        ("INTRADAY_MIN_GAP_DIRECTIONAL", "none"),
        ("INTRADAY_MIN_OPEN_MOVE", "0.020"),
        ("INTRADAY_MIN_RELATIVE_STRENGTH", "0.015"),
        ("INTRADAY_MIN_SPY_OPEN_MOVE", "0.0015"),
        ("INTRADAY_MIN_POOL_BREADTH", "0.68"),
        ("INTRADAY_POOL_LEADER_TOP_K", "2"),
    ):
        monkeypatch.setenv(k, v)
    policy.cache_clear()
    try:
        cfg = policy()
        assert CACHE_VERSION == "intraday_options_v19"
        assert ENTRY_VERSION == "intraday_entry_v8"
        assert SIMULATION_VERSION == "underlying_sim_v8"
        assert cfg.opening_enabled is False
        assert cfg.midday_wave_enabled is True
        assert cfg.atr_scaled_exits is False
        assert cfg.opening_minutes == 5
        assert cfg.opening_min_range_pct == pytest.approx(0.008)
        assert cfg.opening_min_elapsed_minutes == StartPolicy().opening_min_elapsed_minutes
        assert cfg.opening_end_minutes == StartPolicy().opening_end_minutes
        assert cfg.opening_min_efficiency == StartPolicy().opening_min_efficiency
        assert cfg.opening_require_directional_bar is True
        assert cfg.entry_window_minutes == 30
        assert cfg.stop_loss_pct == pytest.approx(0.025)
        assert cfg.take_profit_pct == pytest.approx(0.035)
        assert cfg.profit_lock_trigger_pct == pytest.approx(0.020)
        assert cfg.profit_lock_level_pct == pytest.approx(0.002)
        assert cfg.min_gap_directional is None
        assert cfg.min_open_move == pytest.approx(0.020)
        assert cfg.min_relative_strength == pytest.approx(0.015)
        assert cfg.min_spy_open_move == pytest.approx(0.0015)
        assert cfg.min_pool_breadth == pytest.approx(0.68)
        assert cfg.pool_leader_top_k == 2
        assert CONFIG.max_daily_entries == 1
    finally:
        policy.cache_clear()


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"INTRADAY_MIN_POOL_BREADTH": "1.1"}, "BREADTH"),
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
def test_v7_fixed_wave_exits_stop_profit_lock_tp_and_no_90m_underwater_cut(side):
    vals8 = [100.0 + side * x for x in (0.0, 0.35, 0.70, 1.05, 1.40, 1.80, 2.20, 2.60)]
    nvda8 = _make_bars(vals8, symbol="NVDA.US", wick=Decimal("0.01"))
    spy8 = _make_bars([500.0 + side * x for x in (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05)], symbol="SPY.US")
    peers = _make_peer_pool(nvda8, side=side, nvda_rank=1, breadth_ratio=0.75, count=12)
    t8 = nvda8[-1].bar_time + timedelta(minutes=1, seconds=3)
    r8 = {
        **historical_signal("v7", side),
        **execution_context(nvda8, spy8, peer_bars=peers, settings=V7_POLICY),
    }
    ep = 100.0 + side * 2.65

    # Scenario A: +2.0% floating gain promotes protection to +0.20%, then reversal exits at profit-lock!
    s_lock, _ = transition({}, "NVDA.US", r8, quote(t8, ep), t8, settings=V7_POLICY)
    assert s_lock["position"]["protection"] == pytest.approx(ep * (1.0 - side * 0.025))
    t_95m = t8 + timedelta(minutes=95)
    # V7 does NOT exit underwater at 95m (unlike V6's 90m underwater cut)!
    s_lock, ev_95 = transition(s_lock, "NVDA.US", None, quote(t_95m, ep * (1.0 - side * 0.008)), t_95m, settings=V7_POLICY)
    assert s_lock["position"] and not ev_95
    # Rally to +2.1% triggers BE20_Lock20 (+0.20% lock).
    t_rally = t_95m + timedelta(minutes=10)
    s_lock, ev_rally = transition(
        s_lock, "NVDA.US", None, quote(t_rally, ep * (1.0 + side * 0.021)), t_rally, settings=V7_POLICY
    )
    assert s_lock["position"]["protection"] == pytest.approx(ep * (1.0 + side * 0.002))
    assert s_lock["position"]["protection_stage"] == "profit_lock"
    assert any(e["kind"] == "hold" and "+0.20%锁盈" in e["reason"] for e in ev_rally)
    # Reversal touching +0.15% exits with profit-lock reason and positive return.
    t_rev = t_rally + timedelta(minutes=5)
    s_lock, ev_rev = transition(
        s_lock, "NVDA.US", None, quote(t_rev, ep * (1.0 + side * 0.0015)), t_rev, settings=V7_POLICY
    )
    assert not s_lock["position"]
    tr_lock = next(e["trade"] for e in ev_rev if e["kind"] == "exit")
    assert tr_lock["exit_reason"] == "保本锁盈保护触及" and tr_lock["return_pct"] > 0

    # Scenario B: Direct +3.5% hit exits cleanly at wave take-profit target.
    s_tp, _ = transition({}, "NVDA.US", r8, quote(t8, ep), t8, settings=V7_POLICY)
    t_tp = t8 + timedelta(minutes=30)
    s_tp, ev_tp = transition(s_tp, "NVDA.US", None, quote(t_tp, ep * (1.0 + side * 0.036)), t_tp, settings=V7_POLICY)
    assert not s_tp["position"]
    tr_tp = next(e["trade"] for e in ev_tp if e["kind"] == "exit")
    assert tr_tp["exit_reason"] == "到达波段止盈目标" and tr_tp["return_pct"] >= 3.5

    # Scenario C: -2.5% hit exits cleanly at macro stop loss.
    s_sl, _ = transition({}, "NVDA.US", r8, quote(t8, ep), t8, settings=V7_POLICY)
    t_sl = t8 + timedelta(minutes=15)
    s_sl, ev_sl = transition(s_sl, "NVDA.US", None, quote(t_sl, ep * (1.0 - side * 0.026)), t_sl, settings=V7_POLICY)
    assert not s_sl["position"]
    tr_sl = next(e["trade"] for e in ev_sl if e["kind"] == "exit")
    assert tr_sl["exit_reason"] == "宏观止损触及" and tr_sl["return_pct"] <= -2.5

    # Scenario D: Disabling profit lock (profit_lock_trigger_pct=0) matches pure SL25/TP35.
    no_lock_cfg = replace(V7_POLICY, profit_lock_trigger_pct=0.0, profit_lock_level_pct=0.0)
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


@pytest.mark.parametrize(
    "side,q1,q2,expected_prot",
    [
        (1, 102.10, 100.10, 100.20),
        (-1, 97.90, 99.90, 99.80),
    ],
)
def test_v7_same_minute_quote_sequence_locks_and_exits_at_observed_quote(side, q1, q2, expected_prot):
    # 100 long -> 102.10 raises protection to 100.20 -> 100.10 exits at actual observed 100.10 inside same minute.
    entry_t = START + timedelta(minutes=8, seconds=2)
    state = {
        "symbol": "NVDA.US",
        "trading_date": entry_t.date().isoformat(),
        "calculated_at": entry_t.isoformat(),
        "healthy": True,
        "daily_entry_count": 1,
        "position": {
            "id": "NVDA.US:v7_seq",
            "symbol": "NVDA.US",
            "trading_date": entry_t.date().isoformat(),
            "side": side,
            "kind": "opening_breakout",
            "opportunity_id": "v7:seq",
            "process_id": "v7:seq",
            "version": "underlying_sim_v7",
            "entry_price": 100.0,
            "entry_at": entry_t.isoformat(),
            "entry_price_at": entry_t.isoformat(),
            "invalidation": 100.0 * (1.0 - side * 0.025),
            "protection": 100.0 * (1.0 - side * 0.025),
            "target": 100.0 * (1.0 + side * 0.035),
            "cutoff": (START + timedelta(minutes=380)).isoformat(),
            "peak_gain": 0.0,
            "last_price": 100.0,
            "last_price_at": entry_t.isoformat(),
            "return_pct": 0.0,
            "exit_policy": "v7_fixed_wave",
            "stop_loss_pct": 0.025,
            "take_profit_pct": 0.035,
            "profit_lock_trigger_pct": 0.020,
            "profit_lock_level_pct": 0.002,
        },
    }
    t1 = START + timedelta(minutes=8, seconds=15)
    s1, ev1 = transition(state, "NVDA.US", None, quote(t1, q1), t1)
    assert s1["position"]["protection"] == pytest.approx(expected_prot)
    assert any(e["kind"] == "hold" and "+0.20%锁盈" in e["reason"] for e in ev1)

    t2 = START + timedelta(minutes=8, seconds=35)
    s2, ev2 = transition(s1, "NVDA.US", None, quote(t2, q2), t2)
    assert not s2["position"]
    tr = next(e["trade"] for e in ev2 if e["kind"] == "exit")
    assert tr["exit_reason"] == "保本锁盈保护触及"
    assert tr["protection"] == pytest.approx(expected_prot)
    assert tr["exit_price"] == pytest.approx(q2)


@pytest.mark.parametrize("side", [1, -1])
def test_v7_ten_atr_chase_boundary_and_0959_signal_denied_at_1000(side):
    vals8 = [100.0 + side * x for x in (0.0, 0.35, 0.70, 1.05, 1.40, 1.80, 2.20, 2.60)]
    nvda8 = _make_bars(vals8, symbol="NVDA.US", wick=Decimal("0.01"))
    spy8 = _make_bars([500.0 + side * x for x in (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05)], symbol="SPY.US")
    peers = _make_peer_pool(nvda8, side=side, nvda_rank=1, breadth_ratio=0.75, count=12)
    t8 = nvda8[-1].bar_time + timedelta(minutes=1, seconds=3)
    r8 = {
        **historical_signal("v7", side),
        **execution_context(nvda8, spy8, peer_bars=peers, settings=V7_POLICY),
    }
    b = next(x for x in r8["opportunities"]["branches"] if x["kind"] == "opening_breakout")

    # Exactly at 10.0 ATR boundary -> executable; slightly past 10.0 ATR -> blocked!
    at_edge = b["trigger"] + side * 10.0 * b["atr"]
    over_edge = b["trigger"] + side * 10.01 * b["atr"]
    assert plan(b, r8, at_edge, t8, t8, settings=V7_POLICY)["executable"]
    p_over = plan(b, r8, over_edge, t8, t8, settings=V7_POLICY)
    assert not p_over["executable"] and "冻结执行区间" in p_over["execution_reason"]

    # 09:59 signal (bar 28 closing 09:59) cannot enter when quote only arrives at 10:00 NY under V7_POLICY!
    vals29 = [100.0 + side * (0.30 * i if i < 5 else 1.40 + 0.04 * (i - 4)) for i in range(28)]
    vals29.append(100.0 + side * 2.60)
    nvda29 = _make_bars(vals29, symbol="NVDA.US", wick=Decimal("0.01"))
    spy29 = _make_bars([500.0 + side * 0.04 * i for i in range(29)], symbol="SPY.US")
    peers29 = _make_peer_pool(nvda29, side=side, nvda_rank=1, breadth_ratio=0.75, count=12)
    t_0959 = START + timedelta(minutes=29, seconds=2)
    r29 = {
        **calculate("NVDA.US", nvda29, t_0959, settings=V7_POLICY),
        **execution_context(nvda29, spy29, peer_bars=peers29, settings=V7_POLICY),
    }
    t_1000 = START + timedelta(minutes=30)
    s_late, ev_late = transition(
        {}, "NVDA.US", r29, quote(t_1000, float(nvda29[-1].close) + side * 0.05), t_1000, settings=V7_POLICY
    )
    assert s_late["session_phase"] == "stopped" and not s_late.get("position")
    assert not any(e["kind"] == "entry" for e in ev_late)

    # Early-close day (2025-11-28, 09:30-13:00 NY) sets exit_cutoff to 12:50 NY (17:50 UTC)!
    from datetime import date
    from finance_analysis.market_stream.session import session_bounds

    early_open, early_close = session_bounds("US", date(2025, 11, 28))
    t_early = early_open + timedelta(minutes=10)
    s_early, _ = transition({}, "NVDA.US", None, None, t_early, settings=V7_POLICY)
    assert s_early["exit_cutoff"] == (early_close - timedelta(minutes=10)).isoformat()

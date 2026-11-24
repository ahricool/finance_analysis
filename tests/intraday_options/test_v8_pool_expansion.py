"""V8 QQQ (Nasdaq-100) universe expansion, 2-hour bidirectional drive, ATR ratchet, and bar-0 sanitization tests."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.repositories import intraday_simulation as store
from finance_analysis.interfaces.api.v1.schemas.intraday_options import TrendResult
from finance_analysis.intraday_options.config import (
    BENCHMARK_SYMBOLS,
    EXCLUDED_DUAL_CLASS_SYMBOLS,
    SYMBOLS,
    UNIVERSE_KEY,
    VERSION as CACHE_VERSION,
    normalize_universe_symbols,
)
from finance_analysis.intraday_options.notification import render_trade_notification
from finance_analysis.intraday_options.rules import (
    ENTRY_VERSION,
    SIMULATION_VERSION,
    StartPolicy,
    policy,
    resolve_atr_exit_levels,
)
from finance_analysis.intraday_options.runtime import ranked_opportunity
from finance_analysis.intraday_options.scheduler import _build_round_peer_snapshot
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.intraday_options.simulation import CONFIG, plan, transition
from finance_analysis.intraday_options.structure import execution_context, sanitize_opening_bar
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.market_stream.service import MarketStreamService
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from tests.intraday_options.test_scoring import START
from tests.intraday_options.test_simulation import quote
from tests.intraday_options.test_v7_optimization import _make_bars, _make_peer_pool
from tests.market_stream.fakes import FakeRedis, FakeStreamingClient


def _drive_vals(length: int, target_pct: float = 0.022, side: int = 1) -> list[float]:
    """Generate clean monotone opening drive from 100.0 with OR5 >= 0.8% and high efficiency."""
    assert length >= 6
    or5 = [100.0 + side * 0.25 * i for i in range(5)]  # 0.0 -> 1.00% over 5 bars
    step = (target_pct * 100.0 - 1.0) / max(1, length - 5)
    tail = [100.0 + side * (1.0 + step * (k + 1)) for k in range(length - 5)]
    return [*or5, *tail]


def test_qqq_fallback_universe_integrity_and_normalization():
    assert UNIVERSE_KEY == "us_nasdaq100"
    assert BENCHMARK_SYMBOLS == ("SPY.US", "QQQ.US")
    assert "GOOG.US" in EXCLUDED_DUAL_CLASS_SYMBOLS
    assert len(SYMBOLS) == 102
    assert len(set(SYMBOLS)) == 102
    assert SYMBOLS[0] == "SPY.US"
    assert SYMBOLS[1] == "QQQ.US"
    assert "GOOG.US" not in SYMBOLS
    assert "GOOGL.US" in SYMBOLS
    assert "NVDA.US" in SYMBOLS
    assert "SPCX.US" in SYMBOLS
    assert set(SYMBOLS).isdisjoint({"TQQQ.US", "DRAM.US", "SOXL.US", "IBIT.US"})
    assert all(s.endswith(".US") for s in SYMBOLS)

    normalized = normalize_universe_symbols(
        ["msft.us", "GOOG.US", "GOOGL.US", "SPY.US", "QQQ.US", "NVDA.US", "700.HK", ""]
    )
    assert normalized == ("SPY.US", "QQQ.US", "GOOGL.US", "MSFT.US", "NVDA.US")
    assert normalize_universe_symbols(["GOOG.US", "SPY.US"]) == ()


def test_load_universe_symbols_resolves_db_caches_and_falls_back(monkeypatch):
    store.reset_universe_cache()
    calls = {"count": 0}

    class FakeResolver:
        def resolve_universe(self, key):
            assert key == UNIVERSE_KEY
            calls["count"] += 1
            return tuple(
                SimpleNamespace(code=c) for c in ("NVDA.US", "AAPL.US", "GOOG.US", "GOOGL.US", "MSFT.US")
            )

    monkeypatch.setattr("finance_analysis.database.repositories.universe.UniverseResolver", FakeResolver)
    try:
        first = store.load_universe_symbols()
        assert first == ("SPY.US", "QQQ.US", "AAPL.US", "GOOGL.US", "MSFT.US", "NVDA.US")
        assert calls["count"] == 1
        # Cached within TTL -> zero extra DB hits.
        assert store.load_universe_symbols() == first
        assert calls["count"] == 1

        # Subsequent DB error keeps last known good DB universe instead of shrinking/failing.
        class BrokenResolver:
            def resolve_universe(self, key):
                raise RuntimeError("db unavailable")

        monkeypatch.setattr("finance_analysis.database.repositories.universe.UniverseResolver", BrokenResolver)
        assert store.load_universe_symbols(force_refresh=True) == first

        # Cold start with DB down falls back cleanly to 102-symbol code snapshot.
        store.reset_universe_cache()
        assert store.load_universe_symbols() == SYMBOLS
    finally:
        store.reset_universe_cache()


def test_load_daily_context_strictly_causal_14d_atr_and_fallback(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Instrument.__table__.create(engine)
    StockDaily.__table__.create(engine)

    @contextmanager
    def fake_session_scope():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        store.DatabaseManager, "get_instance", lambda: SimpleNamespace(session_scope=fake_session_scope)
    )
    try:
        with Session(engine) as session:
            nvda = Instrument(
                market="US",
                code="NVDA.US",
                native_code="NVDA",
                name="NVIDIA",
                instrument_type="STOCK",
                currency="USD",
            )
            ipo = Instrument(
                market="US",
                code="NEWIPO.US",
                native_code="NEWIPO",
                name="New IPO",
                instrument_type="STOCK",
                currency="USD",
            )
            session.add_all([nvda, ipo])
            session.flush()
            # 16 prior trading days (< 2026-11-17) with exact 4.0% daily TR on constant close=100.0 (high=102, low=98).
            base_day = date(2026, 10, 20)
            row_id = 1
            for idx in range(16):
                d = base_day + timedelta(days=idx)
                session.add(
                    StockDaily(
                        id=row_id,
                        instrument_id=nvda.id,
                        date=d,
                        open=100.0,
                        high=102.0,
                        low=98.0,
                        close=100.0,
                        volume=1_000_000.0,
                        data_source="test",
                    )
                )
                row_id += 1
            # Same-day (2026-11-17) extreme 50% bar MUST be excluded strictly (< trading_date)!
            session.add(
                StockDaily(
                    id=row_id,
                    instrument_id=nvda.id,
                    date=date(2026, 11, 17),
                    open=100.0,
                    high=150.0,
                    low=50.0,
                    close=145.0,
                    volume=5_000_000.0,
                    data_source="test",
                )
            )
            row_id += 1
            # IPO with only 4 daily bars (< 7 TR samples) -> daily_atr_pct=None, prev_close populated.
            for idx in range(4):
                session.add(
                    StockDaily(
                        id=row_id,
                        instrument_id=ipo.id,
                        date=date(2026, 11, 10) + timedelta(days=idx),
                        open=50.0,
                        high=51.0,
                        low=49.0,
                        close=50.5 + idx,
                        volume=100_000.0,
                        data_source="test",
                    )
                )
                row_id += 1
            session.commit()

        ctx = store.load_daily_context(["NVDA.US", "NEWIPO.US", "MISSING.US"], date(2026, 11, 17))
        assert ctx["NVDA.US"]["daily_atr_pct"] == pytest.approx(0.04)
        assert ctx["NVDA.US"]["atr_samples"] == 14
        assert ctx["NVDA.US"]["prev_close"] == pytest.approx(100.0)
        assert ctx["NVDA.US"]["as_of"] == (base_day + timedelta(days=15)).isoformat()
        assert ctx["NEWIPO.US"]["daily_atr_pct"] is None
        assert ctx["NEWIPO.US"]["atr_samples"] == 3
        assert ctx["NEWIPO.US"]["prev_close"] == pytest.approx(53.5)
        assert ctx["MISSING.US"]["daily_atr_pct"] is None
        assert ctx["MISSING.US"]["prev_close"] is None
    finally:
        engine.dispose()


def test_v8_policy_defaults_and_validation(monkeypatch):
    env_keys = (
        "INTRADAY_OPENING_BREAKOUT",
        "INTRADAY_OPENING_MINUTES",
        "INTRADAY_OPENING_MIN_RANGE_PCT",
        "INTRADAY_OPENING_MIN_ELAPSED_MINUTES",
        "INTRADAY_OPENING_END_MINUTES",
        "INTRADAY_OPENING_MIN_EFFICIENCY",
        "INTRADAY_OPENING_REQUIRE_DIRECTIONAL_BAR",
        "INTRADAY_OPENING_BAR_MAX_WICK_PCT",
        "INTRADAY_EXCLUDE_BENCHMARK_OPENING",
        "INTRADAY_ENTRY_WINDOW_MINUTES",
        "INTRADAY_ATR_SCALED_EXITS",
        "INTRADAY_ATR_FLOOR_PCT",
        "INTRADAY_ATR_CAP_PCT",
        "INTRADAY_ATR_FALLBACK_PCT",
        "INTRADAY_STOP_LOSS_ATR_MULT",
        "INTRADAY_TAKE_PROFIT_ATR_MULT",
        "INTRADAY_RATCHET_TIER1_TRIGGER_ATR",
        "INTRADAY_RATCHET_TIER1_LOCK_ATR",
        "INTRADAY_RATCHET_TIER2_TRIGGER_ATR",
        "INTRADAY_RATCHET_TIER2_LOCK_ATR",
        "INTRADAY_MIN_GAP_DIRECTIONAL",
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
        assert CACHE_VERSION == "intraday_options_v18"
        assert ENTRY_VERSION == "intraday_entry_v8"
        assert SIMULATION_VERSION == "underlying_sim_v8"
        assert cfg.opening_min_elapsed_minutes == 12
        assert cfg.opening_end_minutes == 120
        assert cfg.entry_window_minutes == 120
        assert cfg.opening_min_efficiency == pytest.approx(0.48)
        assert not hasattr(cfg, "opening_direction_mode")
        assert cfg.opening_bar_max_wick_pct == pytest.approx(0.03)
        assert cfg.exclude_benchmark_from_opening is True
        assert cfg.min_gap_directional == pytest.approx(-0.005)
        assert cfg.min_open_move == pytest.approx(0.012)
        assert cfg.min_relative_strength == pytest.approx(0.008)
        assert cfg.min_spy_open_move == pytest.approx(0.0015)
        assert cfg.min_pool_breadth == pytest.approx(0.68)
        assert cfg.pool_leader_top_k == 10
        assert cfg.atr_scaled_exits is True
        assert cfg.atr_floor_pct == pytest.approx(0.012)
        assert cfg.atr_cap_pct == pytest.approx(0.080)
        assert cfg.atr_fallback_pct == pytest.approx(0.030)
        assert cfg.stop_loss_atr_mult == pytest.approx(1.2)
        assert cfg.take_profit_atr_mult == pytest.approx(0.0)
        assert cfg.ratchet_tier1_trigger_atr == pytest.approx(0.50)
        assert cfg.ratchet_tier1_lock_atr == pytest.approx(0.08)
        assert cfg.ratchet_tier2_trigger_atr == pytest.approx(1.20)
        assert cfg.ratchet_tier2_lock_atr == pytest.approx(0.60)
        assert CONFIG.entry_window_minutes == 120
        assert CONFIG.workers == 6

        # Larger pool top-k (e.g. 50) is now accepted (not capped at 28).
        monkeypatch.setenv("INTRADAY_POOL_LEADER_TOP_K", "50")
        policy.cache_clear()
        assert policy().pool_leader_top_k == 50
    finally:
        policy.cache_clear()


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"INTRADAY_MIN_GAP_DIRECTIONAL": "not_a_number"}, "INTRADAY_MIN_GAP_DIRECTIONAL"),
        ({"INTRADAY_ATR_FLOOR_PCT": "0"}, "INTRADAY_ATR_FLOOR_PCT"),
        ({"INTRADAY_ATR_FLOOR_PCT": "0.05", "INTRADAY_ATR_CAP_PCT": "0.02"}, "INTRADAY_ATR_CAP_PCT"),
        ({"INTRADAY_STOP_LOSS_ATR_MULT": "0"}, "INTRADAY_STOP_LOSS_ATR_MULT"),
        ({"INTRADAY_RATCHET_TIER1_TRIGGER_ATR": "0.5", "INTRADAY_RATCHET_TIER1_LOCK_ATR": "0.5"}, "TIER1_LOCK"),
        ({"INTRADAY_RATCHET_TIER2_TRIGGER_ATR": "0.4", "INTRADAY_RATCHET_TIER1_TRIGGER_ATR": "0.5"}, "TIER2_TRIGGER"),
        (
            {"INTRADAY_RATCHET_TIER1_LOCK_ATR": "0.3", "INTRADAY_RATCHET_TIER2_LOCK_ATR": "0.2"},
            "TIER2_LOCK",
        ),
        (
            {"INTRADAY_TAKE_PROFIT_ATR_MULT": "1.0", "INTRADAY_RATCHET_TIER2_TRIGGER_ATR": "1.2"},
            "TAKE_PROFIT_ATR_MULT",
        ),
    ],
)
def test_v8_policy_rejects_invalid_env_combinations(monkeypatch, overrides, match):
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    policy.cache_clear()
    try:
        with pytest.raises(ValueError, match=match):
            policy()
    finally:
        policy.cache_clear()


@pytest.mark.parametrize("side", [1, -1])
def test_v8_two_hour_window_bidirectional_benchmark_exclusion_and_no_counter_gap(side):
    expected_dir = "bullish" if side == 1 else "bearish"

    # 1. Minute 11 (09:41 NY): too early (V8 starts at 09:42 NY = minute 12).
    nvda11 = _make_bars(_drive_vals(11, 0.022, side=side), symbol="NVDA.US")
    t11 = nvda11[-1].bar_time + timedelta(minutes=1, seconds=2)
    r11 = calculate("NVDA.US", nvda11, t11)
    assert not any(b["kind"] == "opening_breakout" for b in r11["opportunities"]["branches"])

    # 2. Minute 12 (09:42 NY): both long and short confirm directly without any direction-mode toggle.
    nvda12 = _make_bars(_drive_vals(12, 0.022, side=side), symbol="NVDA.US")
    t12 = nvda12[-1].bar_time + timedelta(minutes=1, seconds=2)
    base12 = calculate("NVDA.US", nvda12, t12)
    TrendResult.model_validate(base12)
    b12 = next(x for x in base12["opportunities"]["branches"] if x["kind"] == "opening_breakout")
    assert b12["status"] == "confirmed" and b12["direction"] == expected_dir

    # 3. Minute 90 (11:00 NY, inside [09:42, 11:30)): still triggers! Minute 120 (11:30 NY): stopped!
    nvda90 = _make_bars(_drive_vals(90, 0.026, side=side), symbol="NVDA.US")
    t90 = nvda90[-1].bar_time + timedelta(minutes=1, seconds=2)
    r90 = calculate("NVDA.US", nvda90, t90)
    assert any(
        b["kind"] == "opening_breakout" and b["direction"] == expected_dir for b in r90["opportunities"]["branches"]
    )

    nvda120 = _make_bars(_drive_vals(120, 0.028, side=side), symbol="NVDA.US")
    t120 = nvda120[-1].bar_time + timedelta(minutes=1, seconds=2)
    r120 = calculate("NVDA.US", nvda120, t120)
    assert not any(b["kind"] == "opening_breakout" for b in r120["opportunities"]["branches"])

    # 4. Benchmark ETFs (SPY/QQQ) are excluded from opening_breakout simulated entries on both sides.
    spy12 = _make_bars([500.0 + side * 0.15 * i for i in range(12)], symbol="SPY.US")
    peers12 = _make_peer_pool(nvda12, side=side, nvda_rank=1, breadth_ratio=0.75, count=12)
    ok_pre_close = Decimal("100.3") if side == 1 else Decimal("99.7")
    res_nvda = {
        **base12,
        **execution_context(
            nvda12,
            spy12,
            peer_bars=peers12,
            daily_context={"daily_atr_pct": 0.035, "prev_close": float(ok_pre_close)},
            pre_close=ok_pre_close,
        ),
    }
    price12 = float(nvda12[-1].close) + side * 0.05
    p_ok = plan(b12, res_nvda, price12, t12, t12)
    assert p_ok["executable"] is True

    for bench in ("SPY.US", "QQQ.US"):
        res_bench = {**deepcopy(res_nvda), "symbol": bench}
        p_bench = plan(b12, res_bench, price12, t12, t12)
        assert not p_bench["executable"] and "基准指数ETF" in p_bench["execution_reason"]

    # 5. Symmetric no-counter-gap gate: counter-gap > 0.50% rejected; <= 0.50% passes; missing prev_close fails closed!
    # Also verify quote.pre_close takes precedence over DB StockDaily.close (split-safe unadjusted basis).
    bad_pre_close = Decimal("100.65") if side == 1 else Decimal("99.35")
    db_favorable = 99.0 if side == 1 else 101.0
    res_bad_gap = {
        **base12,
        **execution_context(
            nvda12,
            spy12,
            peer_bars=peers12,
            daily_context={"daily_atr_pct": 0.035, "prev_close": db_favorable},
            pre_close=bad_pre_close,
        ),
    }
    assert res_bad_gap["daily_context"]["prev_close_source"] == "quote_pre_close"
    assert res_bad_gap["daily_context"]["gap_return"] == pytest.approx(100.0 / float(bad_pre_close) - 1.0)
    p_bad_gap = plan(b12, res_bad_gap, price12, t12, t12)
    assert not p_bad_gap["executable"] and "隔夜反向跳空过大" in p_bad_gap["execution_reason"]

    res_no_pre = {
        **base12,
        **execution_context(nvda12, spy12, peer_bars=peers12, daily_context={}, pre_close=None),
    }
    p_no_pre = plan(b12, res_no_pre, price12, t12, t12)
    assert not p_no_pre["executable"] and "缺少昨收基准数据" in p_no_pre["execution_reason"]


def test_v8_opening_entry_uses_full_pool_when_peer_history_is_missing():
    nvda = _make_bars(_drive_vals(12, 0.022), symbol="NVDA.US")
    spy = _make_bars([500.0 + 0.05 * i for i in range(12)], symbol="SPY.US")
    now = nvda[-1].bar_time + timedelta(minutes=1, seconds=2)
    result = calculate("NVDA.US", nvda, now)
    branch = next(b for b in result["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    price = float(nvda[-1].close) + 0.05
    peers = _make_peer_pool(nvda, count=100, breadth_ratio=0.75)
    observed_names = list(peers)
    strong_spy = _make_bars([500.0 + 0.15 * i for i in range(12)], symbol="SPY.US")

    def evaluate(count, benchmark, settings=None):
        available = {symbol: peers[symbol] for symbol in observed_names[:count]}
        roster = ("SPY.US", "QQQ.US", *peers)
        peer_snapshot, _ = _build_round_peer_snapshot(available, roster, START, now)
        context = execution_context(nvda, benchmark, peer_snapshot, pre_close=100)
        return context["pool_rank_context"], plan(branch, {**result, **context}, price, now, now, settings=settings)

    # All 10 observed names are rising, but 90 unobserved peers can outrank NVDA.
    rank, candidate = evaluate(10, strong_spy)
    assert rank["pool_size"] == 100 and rank["observed_pool_size"] == 10
    assert rank["long_rank"] == 1 and rank["long_rank_upper"] == 91
    assert rank["breadth_up"] == pytest.approx(0.10)
    assert not candidate["executable"] and "无法确认全池排名" in candidate["execution_reason"]

    # Exactly 10th in the worst case and 75 verified advances meet both guarantees.
    rank, candidate = evaluate(91, spy)
    assert rank["long_rank_upper"] == 10 and rank["breadth_up"] == pytest.approx(0.75)
    assert candidate["executable"]

    # With ranking disabled, peer breadth alone still uses all 100 members.
    _, candidate = evaluate(10, spy, StartPolicy(pool_leader_top_k=0))
    assert not candidate["executable"] and "大盘共振不足" in candidate["execution_reason"]


@pytest.mark.parametrize("side", [1, -1])
def test_v8_atr_clamping_ratchet_tiers_uncapped_eod_and_ranked_opportunity(side):
    cfg = StartPolicy()
    low = resolve_atr_exit_levels(0.005, cfg)
    assert low["daily_atr_pct"] == pytest.approx(0.012) and low["daily_atr_source"] == "stock_daily_14d"
    assert low["stop_loss_pct"] == pytest.approx(0.0144)

    high = resolve_atr_exit_levels(0.120, cfg)
    assert high["daily_atr_pct"] == pytest.approx(0.080) and high["stop_loss_pct"] == pytest.approx(0.096)

    fb = resolve_atr_exit_levels(None, cfg)
    assert fb["daily_atr_pct"] == pytest.approx(0.030) and fb["daily_atr_source"] == "fallback_default"
    assert fb["stop_loss_pct"] == pytest.approx(0.036)

    # Full V8 transition lifecycle with daily_atr_pct = 0.040 (symmetric for long and short):
    # SL = 4.80%, Tier1 = +2.00% -> lock +0.32%, Tier2 = +4.80% -> lock +2.40%, no fixed TP.
    nvda12 = _make_bars(_drive_vals(12, 0.022, side=side), symbol="NVDA.US")
    spy12 = _make_bars([500.0 + side * 0.15 * i for i in range(12)], symbol="SPY.US")
    peers12 = _make_peer_pool(nvda12, side=side, nvda_rank=1, breadth_ratio=0.75, count=12)
    t12 = nvda12[-1].bar_time + timedelta(minutes=1, seconds=2)
    r12 = {
        **calculate("NVDA.US", nvda12, t12),
        **execution_context(
            nvda12,
            spy12,
            peer_bars=peers12,
            daily_context={"daily_atr_pct": 0.040, "prev_close": 100.0},
            pre_close=Decimal("100.0"),
        ),
    }
    ep = 100.0 + side * 2.25
    q_entry = quote(t12, ep)
    state, ev_entry = transition({}, "NVDA.US", r12, q_entry, t12)
    pos = state["position"]
    assert pos is not None and pos["side"] == side and pos["exit_policy"] == "v8_atr_ratchet"
    assert pos["target"] is None
    assert pos["daily_atr_pct"] == pytest.approx(0.040)
    assert pos["daily_atr_source"] == "stock_daily_14d"
    assert pos["invalidation"] == pytest.approx(ep * (1.0 - side * 0.048))
    assert any(e["kind"] == "entry" for e in ev_entry)

    # ranked_opportunity() MUST still match cleanly (daily_atr_source must not clobber branch["atr_source"]).
    ranked = ranked_opportunity(r12, state, t12, q_entry)
    assert ranked is not None and ranked["kind"] == "opening_breakout"
    assert ranked["invalidation"] == pytest.approx(ep * (1.0 - side * 0.048))

    # Scenario A: Tier-1 (+2.1%) -> lock +0.32%, then Tier-2 (+5.0%) -> lock +2.40%, then pullback to +2.30% exits!
    t_a1 = t12 + timedelta(minutes=10)
    s_a, ev_a1 = transition(deepcopy(state), "NVDA.US", None, quote(t_a1, ep * (1.0 + side * 0.021)), t_a1)
    assert s_a["position"]["protection_stage"] == "ratchet_tier1"
    assert s_a["position"]["protection"] == pytest.approx(ep * (1.0 + side * 0.0032))
    assert any(e["kind"] == "hold" and "一档棘轮" in e["reason"] for e in ev_a1)

    t_a2 = t_a1 + timedelta(minutes=20)
    s_a, ev_a2 = transition(s_a, "NVDA.US", None, quote(t_a2, ep * (1.0 + side * 0.050)), t_a2)
    assert s_a["position"]["protection_stage"] == "ratchet_tier2"
    assert s_a["position"]["protection"] == pytest.approx(ep * (1.0 + side * 0.024))
    assert any(e["kind"] == "hold" and "二档棘轮" in e["reason"] for e in ev_a2)

    # Uncapped right tail: +7.5% stays open!
    t_a3 = t_a2 + timedelta(minutes=30)
    s_a, ev_a3 = transition(s_a, "NVDA.US", None, quote(t_a3, ep * (1.0 + side * 0.075)), t_a3)
    assert s_a["position"] is not None and not ev_a3

    # Pullback to +2.30% (below +2.40% lock) exits at observed quote!
    t_a4 = t_a3 + timedelta(minutes=5)
    s_a, ev_a4 = transition(s_a, "NVDA.US", None, quote(t_a4, ep * (1.0 + side * 0.023)), t_a4)
    assert s_a["position"] is None
    tr_a = next(e["trade"] for e in ev_a4 if e["kind"] == "exit")
    assert tr_a["exit_reason"] == "二档棘轮锁盈触及"
    assert tr_a["exit_price"] == pytest.approx(ep * (1.0 + side * 0.023))
    assert tr_a["return_pct"] == pytest.approx(2.3)

    # Scenario B: Direct single-tick jump to +5.2% promotes straight to Tier-2 with one clean event.
    t_b1 = t12 + timedelta(minutes=5)
    s_b, ev_b1 = transition(deepcopy(state), "NVDA.US", None, quote(t_b1, ep * (1.0 + side * 0.052)), t_b1)
    assert s_b["position"]["protection_stage"] == "ratchet_tier2"
    assert s_b["position"]["protection"] == pytest.approx(ep * (1.0 + side * 0.024))
    assert sum(1 for e in ev_b1 if e["kind"] == "hold") == 1

    # Scenario C: Tier-1 lock then reversal to +0.25% exits with "一档保本锁盈触及".
    t_c1 = t12 + timedelta(minutes=5)
    s_c, _ = transition(deepcopy(state), "NVDA.US", None, quote(t_c1, ep * (1.0 + side * 0.022)), t_c1)
    t_c2 = t_c1 + timedelta(minutes=2)
    s_c, ev_c2 = transition(s_c, "NVDA.US", None, quote(t_c2, ep * (1.0 + side * 0.0025)), t_c2)
    assert s_c["position"] is None
    assert next(e["trade"] for e in ev_c2 if e["kind"] == "exit")["exit_reason"] == "一档保本锁盈触及"

    # Scenario D: Initial ATR stop loss (-4.9%) exits with "ATR止损触及".
    t_d1 = t12 + timedelta(minutes=5)
    s_d, ev_d1 = transition(deepcopy(state), "NVDA.US", None, quote(t_d1, ep * (1.0 - side * 0.049)), t_d1)
    assert s_d["position"] is None
    assert next(e["trade"] for e in ev_d1 if e["kind"] == "exit")["exit_reason"] == "ATR止损触及"

    # Scenario E: Notification rendering for V8 ATR ratchet avoids Telegram Markdown hazards.
    entry_ev = next(e for e in ev_entry if e["kind"] == "entry")
    title, body = render_trade_notification(entry_ev, symbol_name="英伟达")
    expected_dir_label = "做多" if side == 1 else "做空"
    assert f"日内模拟开仓 · {expected_dir_label} NVDA.US" in title
    assert "两档ATR棘轮锁盈·尾盘清仓" in body
    assert "14日ATR 4.00%" in body
    assert "浮盈达 +2.00% 锁盈 +0.32%" in body
    assert "浮盈达 +4.80% 锁盈 +2.40%" in body
    assert "_" not in body and "(" not in body and ")" not in body

    # Fallback ATR source must label honestly as 默认ATR rather than 14日ATR.
    fb_ev = deepcopy(entry_ev)
    fb_ev["trade"]["daily_atr_pct"] = 0.030
    fb_ev["trade"]["daily_atr_source"] = "fallback_default"
    _, fb_body = render_trade_notification(fb_ev, symbol_name="英伟达")
    assert "默认ATR 3.00%" in fb_body and "14日ATR" not in fb_body


def test_scheduler_daily_context_does_not_leak_across_trading_days(monkeypatch):
    from finance_analysis.intraday_options import scheduler
    from finance_analysis.integrations.market_data.realtime_state.models import QuoteState

    async def run_case():
        redis = FakeRedis()
        repo = RealtimeStateRepository(redis)
        # Preopen on next trading day (09:10 NY), while bars_by_symbol still holds yesterday's bars.
        yesterday_bars = _make_bars(_drive_vals(12, 0.022, side=1), symbol="NVDA.US", start=START)
        next_day_preopen = START + timedelta(days=1) - timedelta(minutes=20)
        await repo.write_quote(
            QuoteState(
                "NVDA.US",
                trading_date=START.date(),
                last_price=Decimal("102.20"),
                pre_close=Decimal("100.00"),
                event_time=START + timedelta(minutes=12),
                received_at=START + timedelta(minutes=12),
            )
        )
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        seen_results = []

        def fake_process_with_events(symbol, result, q, when):
            if symbol == "NVDA.US" and result is not None:
                seen_results.append(result)
                loop.call_soon_threadsafe(stop_event.set)
            return {"symbol": symbol, "position": None}, []

        # Daily context returned for next_day (contains yesterday's 102.20 close) must NOT attach to yesterday's bars!
        monkeypatch.setattr(scheduler, "SYMBOLS", ("NVDA.US",))
        monkeypatch.setattr(scheduler, "open_retired_symbols", lambda: set())
        monkeypatch.setattr(
            scheduler,
            "load_daily_context",
            lambda syms, d: {
                "NVDA.US": {"daily_atr_pct": 0.05, "prev_close": 102.20, "as_of": START.date().isoformat()}
            },
        )
        monkeypatch.setattr(scheduler, "process_with_events", fake_process_with_events)
        monkeypatch.setattr(scheduler, "utc_now", lambda: next_day_preopen)

        await asyncio.wait_for(scheduler.run(repo, {"NVDA.US": yesterday_bars}, stop_event), timeout=3)
        assert len(seen_results) >= 1
        daily_ctx = seen_results[0]["daily_context"]
        # Yesterday's bar day != today's daily_ctx_day -> DB daily_atr_pct from tomorrow's context must NOT leak!
        assert daily_ctx["daily_atr_pct"] is None
        assert daily_ctx["prev_close_source"] == "quote_pre_close"
        assert daily_ctx["prev_close"] == pytest.approx(100.0)

    asyncio.run(run_case())


def test_bar0_outlier_wick_sanitization_protects_or5_and_vwap_without_mutation():
    vals12 = _drive_vals(12, 0.024, side=1)
    clean_bars = _make_bars(vals12, symbol="NVDA.US", wick=Decimal("0.01"))
    # Inject extreme -22.5% bar-0 outlier low wick (like NVDA bad print at 09:30 NY).
    bad_bar0 = replace(clean_bars[0], low=Decimal("77.50"))
    spiked_bars = [bad_bar0, *clean_bars[1:]]
    original_low = spiked_bars[0].low

    # 1. Pure sanitizer clamps >3% wick to candle body without mutating original CandleState.
    sanitized, changed = sanitize_opening_bar(spiked_bars[0], START, 0.03)
    assert changed is True
    assert sanitized.low == min(bad_bar0.open, bad_bar0.close)
    assert spiked_bars[0].low == original_low  # Never mutated!

    # Normal <=3% wick is untouched.
    normal_bar0 = replace(clean_bars[0], low=Decimal("98.50"), high=Decimal("101.50"))
    untouched, changed_norm = sanitize_opening_bar(normal_bar0, START, 0.03)
    assert changed_norm is False and untouched is normal_bar0

    # 2. OR5 width/ATR and session VWAP remain protected despite the -22.5% bar-0 print.
    t12 = spiked_bars[-1].bar_time + timedelta(minutes=1, seconds=2)
    res_clean = calculate("NVDA.US", clean_bars, t12)
    res_spiked = calculate("NVDA.US", spiked_bars, t12)
    b_clean = next(b for b in res_clean["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    b_spiked = next(b for b in res_spiked["opportunities"]["branches"] if b["kind"] == "opening_breakout")
    # Without sanitization, OR5 width would be >23 instead of ~1.0!
    assert (b_spiked["structure_high"] - b_spiked["structure_low"]) < 1.5
    assert b_spiked["trigger"] == pytest.approx(b_clean["trigger"])
    assert spiked_bars[0].low == original_low

    ctx_clean = execution_context(clean_bars)
    ctx_spiked = execution_context(spiked_bars)
    assert ctx_spiked["market_context"]["opening_bar_sanitized"] is True
    assert ctx_clean["market_context"]["opening_bar_sanitized"] is False
    # Sanitized VWAP stays very close to clean VWAP (instead of dropping sharply from 77.50 print).
    assert abs(ctx_spiked["market_context"]["vwap"] - ctx_clean["market_context"]["vwap"]) < 0.05

    # 3. Disabling sanitization (opening_bar_max_wick_pct=0.0) keeps raw bar-0 low.
    raw_cfg = StartPolicy(opening_bar_max_wick_pct=0.0)
    ctx_raw = execution_context(spiked_bars, settings=raw_cfg)
    assert ctx_raw["market_context"]["opening_bar_sanitized"] is False
    assert ctx_raw["market_context"]["vwap"] < ctx_spiked["market_context"]["vwap"] - 0.5


def test_scheduler_shared_peer_snapshot_excludes_benchmarks_and_service_syncs_isolated(monkeypatch):
    nvda = _make_bars(_drive_vals(12, 0.025, side=1), symbol="NVDA.US")
    spy = _make_bars(_drive_vals(12, 0.040, side=1), symbol="SPY.US")
    qqq = _make_bars(_drive_vals(12, 0.035, side=1), symbol="QQQ.US")
    now = nvda[-1].bar_time + timedelta(minutes=1, seconds=3)
    bars_map = {"SPY.US": spy, "QQQ.US": qqq, "NVDA.US": nvda}
    peer_closed, sig = _build_round_peer_snapshot(bars_map, ("SPY.US", "QQQ.US", "NVDA.US"), START, now)
    assert "SPY.US" not in peer_closed
    assert "QQQ.US" not in peer_closed
    assert "NVDA.US" in peer_closed and len(peer_closed["NVDA.US"]) > 0
    assert sig == _build_round_peer_snapshot(bars_map, ("SPY.US", "QQQ.US", "NVDA.US"), START, now)[1]

    # MarketStreamService dynamically updates SubscriptionManager.isolated_symbols from load_universe_symbols().
    monkeypatch.setattr(store, "load_universe_symbols", lambda: ("SPY.US", "QQQ.US", "NEWNDX.US"))
    service = MarketStreamService(
        config=MarketStreamConfig(redis_url="redis://fake"),
        repository=RealtimeStateRepository(FakeRedis()),
        client_factory=FakeStreamingClient,
    )
    asyncio.run(service._sync_isolated_symbols())
    assert service.manager.isolated_symbols == frozenset({"SPY.US", "QQQ.US", "NEWNDX.US"})


def test_existing_v7_open_position_exits_cleanly_under_v8_default_policy():
    # An open V7 position created before upgrade continues using v7_fixed_wave under V8 default policy!
    entry_t = START + timedelta(minutes=10)
    v7_state = {
        "symbol": "NVDA.US",
        "trading_date": entry_t.date().isoformat(),
        "calculated_at": entry_t.isoformat(),
        "healthy": True,
        "daily_entry_count": 1,
        "position": {
            "id": "NVDA.US:v7_upgrade",
            "symbol": "NVDA.US",
            "trading_date": entry_t.date().isoformat(),
            "side": 1,
            "kind": "opening_breakout",
            "opportunity_id": "v7:upgrade",
            "process_id": "v7:upgrade",
            "version": "underlying_sim_v7",
            "entry_price": 100.0,
            "entry_at": entry_t.isoformat(),
            "entry_price_at": entry_t.isoformat(),
            "invalidation": 97.5,
            "protection": 97.5,
            "target": 103.5,
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
    t_tp = entry_t + timedelta(minutes=20)
    s_done, ev = transition(json.loads(json.dumps(v7_state)), "NVDA.US", None, quote(t_tp, 103.6), t_tp)
    assert s_done["position"] is None
    tr = next(e["trade"] for e in ev if e["kind"] == "exit")
    assert tr["exit_reason"] == "到达波段止盈目标"

"""Provisional, versioned shape/execution limits. Scores are not probabilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from finance_analysis.config import env_bool, env_float, env_int, env_str, load_env

ENTRY_VERSION = "intraday_entry_v8"
SIMULATION_VERSION = "underlying_sim_v8"


@dataclass(frozen=True)
class EntryRule:
    confirm_atr: float
    entry_max_atr: float = 1.0
    extended_atr: float = 2.0
    failure_atr: float = .75
    lifetime: int = 15
    max_risk_atr: float | None = None


START_KINDS = ("opening_breakout", "pivot_breakout", "midday_wave_breakout")
START_RULE = EntryRule(.15, entry_max_atr=1, failure_atr=.75, lifetime=5, max_risk_atr=1.75)
OPENING_RULE = EntryRule(.0, entry_max_atr=10.0, extended_atr=12.0, failure_atr=1.15, lifetime=2, max_risk_atr=None)
MIDDAY_WAVE_RULE = EntryRule(.20, entry_max_atr=2.0, extended_atr=2.8, failure_atr=1.15, lifetime=10, max_risk_atr=3.15)
RULES = {
    "opening_breakout": OPENING_RULE,
    "midday_wave_breakout": MIDDAY_WAVE_RULE,
    "pivot_breakout": START_RULE,
    "box_breakout": EntryRule(.2, entry_max_atr=1.5),
    "box_retest": EntryRule(.2),
    "trend_recovery": EntryRule(.1),
    "trend_continuation": EntryRule(.15, entry_max_atr=.8, extended_atr=1.5, lifetime=10, max_risk_atr=2.0),
}


@dataclass(frozen=True)
class ContinuationConfig:
    background: int = 30
    minimum_background: int = 16  # At least 15 observed adjacent true ranges.
    stability: float = .6
    efficiency: float = .35
    advance_atr: float = 1.5
    structure_bars: int = 3
    maximum_structure_minutes: int = 6
    width_atr: float = 1.5
    pullback_atr: float = 1.2
    forward_drift_atr: float = .25
    stop_buffer_atr: float = .1
    volatility_bars: int = 20
    minimum_volatility_samples: int = 15
    strong_break_atr: float = .35
    strong_body_fraction: float = .65
    strong_close_location: float = .8
    maximum_break_range_atr: float = 1.8
    rearm_advance_atr: float = .5
    trend_guard_bars: int = 5


CONTINUATION = ContinuationConfig()


def entry_interval(branch):
    rule = RULES[branch["kind"]]
    side = 1 if branch["direction"] == "bullish" else -1
    return sorted(branch["trigger"] + side * x * branch["atr"]
                  for x in (rule.confirm_atr, rule.entry_max_atr))


def plan_order(branch):
    """Same deterministic quality/kind/identity order for execution and ranking."""
    return (-(branch.get("quality_score") or 0), branch["kind"], branch["structure_id"])


@dataclass(frozen=True)
class StartPolicy:
    opening_enabled: bool = True
    pivot_enabled: bool = False
    midday_wave_enabled: bool = False
    box_enabled: bool = False
    continuation_enabled: bool = False
    recovery_enabled: bool = False
    opening_minutes: int = 5
    opening_min_range_pct: float = .0080
    opening_min_elapsed_minutes: int = 12
    opening_end_minutes: int = 120
    opening_min_efficiency: float = .48
    opening_require_directional_bar: bool = True
    opening_bar_max_wick_pct: float = .0300
    exclude_benchmark_from_opening: bool = True
    opening_level_minutes: int = 85
    entry_window_minutes: int = 120
    level_minutes: int = 30
    pivot_atr_period: int = 20
    pivot_atr_minimum: int = 10
    midday_window_minutes: int = 60
    midday_min_bars: int = 30
    midday_min_width_pct: float = .012
    midday_max_width_pct: float = .050
    midday_max_efficiency: float = .55
    midday_start_minutes: int = 50
    midday_end_minutes: int = 150
    midday_require_session_extreme: bool = True
    midday_session_extreme_tolerance: float = .0015
    strong_break_atr: float = .45
    strong_body_fraction: float = .60
    structure_quality: float = 75.
    use_pivot_target: bool = False
    # V8 two-tier daily-ATR ratchet exit (default enabled; set atr_scaled_exits=False to fall back to V7 fixed wave).
    atr_scaled_exits: bool = True
    atr_floor_pct: float = .0120
    atr_cap_pct: float = .0800
    atr_fallback_pct: float = .0300
    stop_loss_atr_mult: float = 1.20
    take_profit_atr_mult: float = 0.0
    ratchet_tier1_trigger_atr: float = .50
    ratchet_tier1_lock_atr: float = .08
    ratchet_tier2_trigger_atr: float = 1.20
    ratchet_tier2_lock_atr: float = .60
    # Legacy V7 fixed-wave parameters (used when atr_scaled_exits=False).
    stop_loss_pct: float = .0250
    take_profit_pct: float = 0.0
    profit_lock_trigger_pct: float = .0200
    profit_lock_level_pct: float = .0020
    minimum_return: float = 0.0
    minimum_rr: float = 0.0
    minimum_risk_return: float = 0.0
    maximum_risk_return: float = 0.0
    require_vwap: bool = True
    require_spy_alignment: bool = True
    min_gap_directional: float | None = -.0050
    min_relative_strength: float = .0080
    min_open_move: float = .0120
    min_spy_open_move: float = .0015
    min_pool_breadth: float = .68
    pool_leader_top_k: int = 10


def resolve_atr_exit_levels(daily_atr_pct: float | None, cfg: StartPolicy) -> dict[str, Any]:
    """Resolve causal 14-day Daily ATR% clamped to [atr_floor_pct, atr_cap_pct] into exit percentages."""
    raw_atr: float | None = None
    if daily_atr_pct is not None:
        try:
            parsed = float(daily_atr_pct)
        except (TypeError, ValueError):
            parsed = float("nan")
        if math.isfinite(parsed) and parsed > 0:
            raw_atr = parsed
    atr_source = "stock_daily_14d" if raw_atr is not None else "fallback_default"
    base_atr = raw_atr if raw_atr is not None else cfg.atr_fallback_pct
    effective_atr = min(max(base_atr, cfg.atr_floor_pct), cfg.atr_cap_pct)
    return {
        "daily_atr_pct": effective_atr,
        "raw_daily_atr_pct": raw_atr,
        "daily_atr_source": atr_source,
        "stop_loss_pct": cfg.stop_loss_atr_mult * effective_atr,
        "take_profit_pct": cfg.take_profit_atr_mult * effective_atr,
        "ratchet_tier1_trigger_pct": cfg.ratchet_tier1_trigger_atr * effective_atr,
        "ratchet_tier1_lock_pct": cfg.ratchet_tier1_lock_atr * effective_atr,
        "ratchet_tier2_trigger_pct": cfg.ratchet_tier2_trigger_atr * effective_atr,
        "ratchet_tier2_lock_pct": cfg.ratchet_tier2_lock_atr * effective_atr,
    }


def _parse_optional_gap_threshold(default: float | None) -> float | None:
    raw = env_str("INTRADAY_MIN_GAP_DIRECTIONAL", "")
    if not raw:
        return default
    if raw.lower() in {"none", "off", "disabled", "false"}:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid INTRADAY_MIN_GAP_DIRECTIONAL: {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError("INTRADAY_MIN_GAP_DIRECTIONAL must be finite")
    if value <= -1.0:
        return None
    return value


@lru_cache(maxsize=1)
def policy():
    load_env()
    defaults = StartPolicy()
    floor = env_float("INTRADAY_MIN_TARGET_RETURN", defaults.minimum_return, minimum=0)
    rr = env_float("INTRADAY_MIN_REWARD_RISK", defaults.minimum_rr, minimum=0)
    min_risk = env_float("INTRADAY_MIN_RISK_RETURN", defaults.minimum_risk_return, minimum=0)
    max_risk = env_float("INTRADAY_MAX_RISK_RETURN", defaults.maximum_risk_return, minimum=0)
    min_or_range = env_float("INTRADAY_OPENING_MIN_RANGE_PCT", defaults.opening_min_range_pct, minimum=0)
    min_or_eff = env_float("INTRADAY_OPENING_MIN_EFFICIENCY", defaults.opening_min_efficiency, minimum=0)
    max_bar0_wick = env_float("INTRADAY_OPENING_BAR_MAX_WICK_PCT", defaults.opening_bar_max_wick_pct, minimum=0)
    min_rs = env_float("INTRADAY_MIN_RELATIVE_STRENGTH", defaults.min_relative_strength, minimum=0)
    min_open = env_float("INTRADAY_MIN_OPEN_MOVE", defaults.min_open_move, minimum=0)
    min_spy_open = env_float("INTRADAY_MIN_SPY_OPEN_MOVE", defaults.min_spy_open_move, minimum=0)
    min_breadth = env_float("INTRADAY_MIN_POOL_BREADTH", defaults.min_pool_breadth, minimum=0)
    min_gap = _parse_optional_gap_threshold(defaults.min_gap_directional)
    stop_pct = env_float("INTRADAY_STOP_LOSS_PCT", defaults.stop_loss_pct, minimum=0)
    tp_pct = env_float("INTRADAY_TAKE_PROFIT_PCT", defaults.take_profit_pct, minimum=0)
    lock_trig = env_float("INTRADAY_PROFIT_LOCK_TRIGGER_PCT", defaults.profit_lock_trigger_pct, minimum=0)
    lock_lvl = env_float("INTRADAY_PROFIT_LOCK_LEVEL_PCT", defaults.profit_lock_level_pct, minimum=0)
    atr_scaled = env_bool("INTRADAY_ATR_SCALED_EXITS", defaults.atr_scaled_exits)
    atr_floor = env_float("INTRADAY_ATR_FLOOR_PCT", defaults.atr_floor_pct, minimum=0)
    atr_cap = env_float("INTRADAY_ATR_CAP_PCT", defaults.atr_cap_pct, minimum=0)
    atr_fallback = env_float("INTRADAY_ATR_FALLBACK_PCT", defaults.atr_fallback_pct, minimum=0)
    sl_atr_mult = env_float("INTRADAY_STOP_LOSS_ATR_MULT", defaults.stop_loss_atr_mult, minimum=0)
    tp_atr_mult = env_float("INTRADAY_TAKE_PROFIT_ATR_MULT", defaults.take_profit_atr_mult, minimum=0)
    t1_trig_atr = env_float("INTRADAY_RATCHET_TIER1_TRIGGER_ATR", defaults.ratchet_tier1_trigger_atr, minimum=0)
    t1_lock_atr = env_float("INTRADAY_RATCHET_TIER1_LOCK_ATR", defaults.ratchet_tier1_lock_atr, minimum=0)
    t2_trig_atr = env_float("INTRADAY_RATCHET_TIER2_TRIGGER_ATR", defaults.ratchet_tier2_trigger_atr, minimum=0)
    t2_lock_atr = env_float("INTRADAY_RATCHET_TIER2_LOCK_ATR", defaults.ratchet_tier2_lock_atr, minimum=0)
    opening_min_elapsed = env_int(
        "INTRADAY_OPENING_MIN_ELAPSED_MINUTES", defaults.opening_min_elapsed_minutes, minimum=5, maximum=60
    )
    opening_end = env_int("INTRADAY_OPENING_END_MINUTES", defaults.opening_end_minutes, minimum=5, maximum=240)
    entry_window = env_int("INTRADAY_ENTRY_WINDOW_MINUTES", defaults.entry_window_minutes, minimum=5, maximum=300)
    if not all(
        math.isfinite(v)
        for v in (
            floor, rr, min_risk, max_risk, min_or_range, min_or_eff, max_bar0_wick,
            min_rs, min_open, min_spy_open, min_breadth, stop_pct, tp_pct, lock_trig, lock_lvl,
            atr_floor, atr_cap, atr_fallback, sl_atr_mult, tp_atr_mult,
            t1_trig_atr, t1_lock_atr, t2_trig_atr, t2_lock_atr,
        )
    ):
        raise ValueError("Intraday thresholds must be finite")
    if max_risk > 0 and max_risk < min_risk:
        raise ValueError("INTRADAY_MAX_RISK_RETURN must be >= INTRADAY_MIN_RISK_RETURN")
    if min_or_eff > 1.0:
        raise ValueError("INTRADAY_OPENING_MIN_EFFICIENCY must be <= 1.0")
    if min_breadth > 1.0:
        raise ValueError("INTRADAY_MIN_POOL_BREADTH must be <= 1.0")
    if opening_end < opening_min_elapsed:
        raise ValueError("INTRADAY_OPENING_END_MINUTES must be >= INTRADAY_OPENING_MIN_ELAPSED_MINUTES")
    if lock_trig > 0 and lock_lvl >= lock_trig:
        raise ValueError("INTRADAY_PROFIT_LOCK_LEVEL_PCT must be < INTRADAY_PROFIT_LOCK_TRIGGER_PCT")
    if tp_pct > 0 and lock_trig >= tp_pct:
        raise ValueError("INTRADAY_PROFIT_LOCK_TRIGGER_PCT must be < INTRADAY_TAKE_PROFIT_PCT")
    if atr_floor <= 0:
        raise ValueError("INTRADAY_ATR_FLOOR_PCT must be > 0")
    if atr_cap < atr_floor:
        raise ValueError("INTRADAY_ATR_CAP_PCT must be >= INTRADAY_ATR_FLOOR_PCT")
    if atr_fallback <= 0:
        raise ValueError("INTRADAY_ATR_FALLBACK_PCT must be > 0")
    if atr_scaled:
        if sl_atr_mult <= 0:
            raise ValueError("INTRADAY_STOP_LOSS_ATR_MULT must be > 0 when INTRADAY_ATR_SCALED_EXITS=true")
        if t1_trig_atr > 0 and t1_lock_atr >= t1_trig_atr:
            raise ValueError("INTRADAY_RATCHET_TIER1_LOCK_ATR must be < INTRADAY_RATCHET_TIER1_TRIGGER_ATR")
        if t2_trig_atr > 0 and t2_lock_atr >= t2_trig_atr:
            raise ValueError("INTRADAY_RATCHET_TIER2_LOCK_ATR must be < INTRADAY_RATCHET_TIER2_TRIGGER_ATR")
        if t1_trig_atr > 0 and t2_trig_atr > 0:
            if t2_trig_atr <= t1_trig_atr:
                raise ValueError("INTRADAY_RATCHET_TIER2_TRIGGER_ATR must be > INTRADAY_RATCHET_TIER1_TRIGGER_ATR")
            if t2_lock_atr < t1_lock_atr:
                raise ValueError("INTRADAY_RATCHET_TIER2_LOCK_ATR must be >= INTRADAY_RATCHET_TIER1_LOCK_ATR")
        if tp_atr_mult > 0 and max(t1_trig_atr, t2_trig_atr) >= tp_atr_mult:
            raise ValueError("INTRADAY_RATCHET trigger ATR multipliers must be < INTRADAY_TAKE_PROFIT_ATR_MULT")
    return StartPolicy(
        opening_enabled=env_bool("INTRADAY_OPENING_BREAKOUT", defaults.opening_enabled),
        pivot_enabled=env_bool("INTRADAY_PIVOT_BREAKOUT", defaults.pivot_enabled),
        midday_wave_enabled=env_bool("INTRADAY_MIDDAY_WAVE_BREAKOUT", defaults.midday_wave_enabled),
        box_enabled=env_bool("INTRADAY_BOX_BREAKOUT", defaults.box_enabled),
        continuation_enabled=env_bool("INTRADAY_TREND_CONTINUATION", defaults.continuation_enabled),
        recovery_enabled=env_bool("INTRADAY_TREND_RECOVERY", defaults.recovery_enabled),
        opening_minutes=env_int("INTRADAY_OPENING_MINUTES", defaults.opening_minutes, minimum=5, maximum=15),
        opening_min_range_pct=min_or_range,
        opening_min_elapsed_minutes=opening_min_elapsed,
        opening_end_minutes=opening_end,
        opening_min_efficiency=min_or_eff,
        opening_require_directional_bar=env_bool(
            "INTRADAY_OPENING_REQUIRE_DIRECTIONAL_BAR", defaults.opening_require_directional_bar
        ),
        opening_bar_max_wick_pct=max_bar0_wick,
        exclude_benchmark_from_opening=env_bool(
            "INTRADAY_EXCLUDE_BENCHMARK_OPENING", defaults.exclude_benchmark_from_opening
        ),
        entry_window_minutes=entry_window,
        use_pivot_target=env_bool("INTRADAY_USE_PIVOT_TARGET", defaults.use_pivot_target),
        atr_scaled_exits=atr_scaled,
        atr_floor_pct=atr_floor,
        atr_cap_pct=atr_cap,
        atr_fallback_pct=atr_fallback,
        stop_loss_atr_mult=sl_atr_mult,
        take_profit_atr_mult=tp_atr_mult,
        ratchet_tier1_trigger_atr=t1_trig_atr,
        ratchet_tier1_lock_atr=t1_lock_atr,
        ratchet_tier2_trigger_atr=t2_trig_atr,
        ratchet_tier2_lock_atr=t2_lock_atr,
        stop_loss_pct=stop_pct,
        take_profit_pct=tp_pct,
        profit_lock_trigger_pct=lock_trig,
        profit_lock_level_pct=lock_lvl,
        minimum_return=floor,
        minimum_rr=rr,
        minimum_risk_return=min_risk,
        maximum_risk_return=max_risk,
        require_vwap=env_bool("INTRADAY_REQUIRE_VWAP", defaults.require_vwap),
        require_spy_alignment=env_bool("INTRADAY_REQUIRE_SPY_ALIGNMENT", defaults.require_spy_alignment),
        min_gap_directional=min_gap,
        min_relative_strength=min_rs,
        min_open_move=min_open,
        min_spy_open_move=min_spy_open,
        min_pool_breadth=min_breadth,
        pool_leader_top_k=env_int("INTRADAY_POOL_LEADER_TOP_K", defaults.pool_leader_top_k, minimum=0, maximum=200),
    )

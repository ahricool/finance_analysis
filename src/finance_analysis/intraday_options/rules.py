"""Provisional, versioned shape/execution limits. Scores are not probabilities."""

import math
from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config import env_bool, env_float, env_int, load_env

ENTRY_VERSION = "intraday_entry_v5"
SIMULATION_VERSION = "underlying_sim_v5"


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
OPENING_RULE = EntryRule(.20, entry_max_atr=1.8, extended_atr=2.5, failure_atr=.85, lifetime=10, max_risk_atr=2.65)
MIDDAY_WAVE_RULE = EntryRule(.20, entry_max_atr=1.6, extended_atr=2.5, failure_atr=.85, lifetime=10, max_risk_atr=2.45)
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
    midday_wave_enabled: bool = True
    recovery_enabled: bool = False
    opening_minutes: int = 5
    opening_min_range_pct: float = .0035
    opening_level_minutes: int = 85
    level_minutes: int = 30
    pivot_atr_period: int = 20
    pivot_atr_minimum: int = 10
    midday_window_minutes: int = 40
    midday_min_bars: int = 30
    midday_min_width_pct: float = .005
    midday_max_width_pct: float = .030
    midday_max_efficiency: float = .60
    midday_start_minutes: int = 35
    midday_end_minutes: int = 260
    strong_break_atr: float = .40
    strong_body_fraction: float = .60
    structure_quality: float = 75.
    use_pivot_target: bool = False
    minimum_return: float = 0.0
    minimum_rr: float = 0.0
    minimum_risk_return: float = .003
    require_vwap: bool = True
    require_spy_alignment: bool = True
    min_relative_strength: float = .002


@lru_cache(maxsize=1)
def policy():
    load_env()
    defaults = StartPolicy()
    floor = env_float("INTRADAY_MIN_TARGET_RETURN", defaults.minimum_return, minimum=0)
    rr = env_float("INTRADAY_MIN_REWARD_RISK", defaults.minimum_rr, minimum=0)
    min_risk = env_float("INTRADAY_MIN_RISK_RETURN", defaults.minimum_risk_return, minimum=0)
    min_or_range = env_float("INTRADAY_OPENING_MIN_RANGE_PCT", defaults.opening_min_range_pct, minimum=0)
    min_rs = env_float("INTRADAY_MIN_RELATIVE_STRENGTH", defaults.min_relative_strength, minimum=0)
    if not all(math.isfinite(v) for v in (floor, rr, min_risk, min_or_range, min_rs)):
        raise ValueError("Intraday thresholds must be finite")
    return StartPolicy(
        opening_enabled=env_bool("INTRADAY_OPENING_BREAKOUT", defaults.opening_enabled),
        pivot_enabled=env_bool("INTRADAY_PIVOT_BREAKOUT", defaults.pivot_enabled),
        midday_wave_enabled=env_bool("INTRADAY_MIDDAY_WAVE_BREAKOUT", defaults.midday_wave_enabled),
        recovery_enabled=env_bool("INTRADAY_TREND_RECOVERY", defaults.recovery_enabled),
        opening_minutes=env_int("INTRADAY_OPENING_MINUTES", defaults.opening_minutes, minimum=5, maximum=15),
        opening_min_range_pct=min_or_range,
        use_pivot_target=env_bool("INTRADAY_USE_PIVOT_TARGET", defaults.use_pivot_target),
        minimum_return=floor,
        minimum_rr=rr,
        minimum_risk_return=min_risk,
        require_vwap=env_bool("INTRADAY_REQUIRE_VWAP", defaults.require_vwap),
        require_spy_alignment=env_bool("INTRADAY_REQUIRE_SPY_ALIGNMENT", defaults.require_spy_alignment),
        min_relative_strength=min_rs,
    )

"""Provisional, versioned shape/execution limits. Scores are not probabilities."""

import math
from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config import env_bool, env_float, env_int, load_env

ENTRY_VERSION = "intraday_entry_v4"
SIMULATION_VERSION = "underlying_sim_v4"


@dataclass(frozen=True)
class EntryRule:
    confirm_atr: float
    entry_max_atr: float = 1.0
    extended_atr: float = 2.0
    failure_atr: float = .75
    lifetime: int = 15
    max_risk_atr: float | None = None


START_KINDS = ("opening_breakout", "pivot_breakout")
START_RULE = EntryRule(.15, entry_max_atr=1, failure_atr=.75, lifetime=5, max_risk_atr=1.75)
RULES = {
    "opening_breakout": START_RULE,
    "pivot_breakout": START_RULE,
    "box_breakout": EntryRule(.2),
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
    pivot_enabled: bool = True
    opening_minutes: int = 5
    level_minutes: int = 30
    pivot_atr_period: int = 20
    pivot_atr_minimum: int = 10
    structure_quality: float = 75.
    minimum_return: float = .001
    minimum_rr: float = .5


@lru_cache(maxsize=1)
def policy():
    load_env()
    defaults = StartPolicy()
    floor = env_float("INTRADAY_MIN_TARGET_RETURN", defaults.minimum_return, minimum=0)
    rr = env_float("INTRADAY_MIN_REWARD_RISK", defaults.minimum_rr, minimum=0)
    if not all(math.isfinite(v) for v in (floor, rr)):
        raise ValueError("Intraday target thresholds must be finite")
    return StartPolicy(
        opening_enabled=env_bool("INTRADAY_OPENING_BREAKOUT", True),
        pivot_enabled=env_bool("INTRADAY_PIVOT_BREAKOUT", True),
        opening_minutes=env_int("INTRADAY_OPENING_MINUTES", 5, minimum=5, maximum=15),
        minimum_return=floor,
        minimum_rr=rr,
    )

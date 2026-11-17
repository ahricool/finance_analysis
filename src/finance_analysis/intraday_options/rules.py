"""Provisional, versioned shape/execution limits. Scores are not probabilities."""

from dataclasses import dataclass

ENTRY_VERSION = "intraday_entry_v3_2"
SIMULATION_VERSION = "underlying_sim_v3_2"


@dataclass(frozen=True)
class EntryRule:
    confirm_atr: float
    entry_max_atr: float = 1.0
    extended_atr: float = 2.0
    failure_atr: float = .75
    lifetime: int = 15
    max_risk_atr: float | None = None


RULES = {
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

"""Price-based trend states, independent of positions and market allocation."""

from typing import Any, Mapping

from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .models import StrategyDecision

ESTABLISHED_STATES = {"CANDIDATE", "TRENDING", "WEAKENING"}


def transition_state(
    row: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> StrategyDecision:
    """Classify today's trend; prior trend state only distinguishes deterioration."""
    close = float(row["reference_price"])
    established = (previous or {}).get("state") in ESTABLISHED_STATES
    broken = close < float(row["previous_low_10"]) or (
        close < float(row["ma20"]) and float(row["ma20_slope"]) <= 0
    )
    if broken and (established or (previous or {}).get("state") == "BROKEN"):
        return StrategyDecision("BROKEN", ["price broke the prior 10-session low or declining MA20"])
    weak = (
        not row["trend_candidate"]
        or row["trend_score"] < config.healthy_trend_score
        or row["rs_score"] < config.healthy_rs_score
        or close < row["ma10"]
    )
    if established and weak:
        return StrategyDecision("WEAKENING", ["trend structure, score, relative strength or MA10 weakened"])
    if established:
        return StrategyDecision("TRENDING", ["established trend remains healthy"])
    if row["is_candidate"]:
        return StrategyDecision("CANDIDATE", ["trend, relative strength, setup and alpha meet candidate thresholds"])
    if row["trend_candidate"]:
        return StrategyDecision("WATCHING", ["trend is forming; candidate conditions are incomplete"])
    return StrategyDecision("IDLE", ["no clear trend"])

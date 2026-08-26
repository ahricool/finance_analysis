"""State classification with an explicit, stable priority order."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig

STATE_PRIORITY = ("EXHAUSTED", "COOLING", "EMERGING", "STRONG", "TRENDING", "WEAK", "NEUTRAL")


def is_overheated(row: Mapping[str, Any], config: ETFRotationConfig = DEFAULT_CONFIG) -> bool:
    return (
        float(row["ret_1d"]) > config.daily_overheat_threshold
        or float(row["ma20_ratio"]) >= config.ma20_penalty_thresholds[0][0]
    )


def classify_state(
    row: Mapping[str, Any],
    momentum_score: float,
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> str:
    """Apply EXHAUSTED > COOLING > EMERGING > STRONG > TRENDING > WEAK > NEUTRAL."""
    rank_change = row.get("rank_change_5d")
    acceleration = float(row["momentum_acceleration"])
    if momentum_score >= 80 and is_overheated(row, config):
        return "EXHAUSTED"
    if momentum_score >= 70 and acceleration < 0 and rank_change is not None and int(rank_change) < 0:
        return "COOLING"
    if int(row["rank_5d"]) <= 10 and rank_change is not None and int(rank_change) >= 10 and acceleration > 0:
        return "EMERGING"
    if momentum_score >= 80:
        return "STRONG"
    if (
        float(row["pct_rank_5d"]) >= 80
        and float(row["pct_rank_10d"]) >= 70
        and float(row["pct_rank_30d"]) >= 60
    ):
        return "TRENDING"
    if momentum_score < 40:
        return "WEAK"
    return "NEUTRAL"


__all__ = ["STATE_PRIORITY", "classify_state", "is_overheated"]

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
    composite = float(row.get("composite_score") if row.get("composite_score") is not None else momentum_score)
    rank_change = row.get("rank_change_5d")
    trend_acceleration = float(row.get("trend_acceleration", row.get("momentum_acceleration", 0.0)))
    acceleration_score = float(row.get("acceleration_score") or 0.0)
    trend_quality_score = float(row.get("trend_quality_score") or 0.0)
    absolute_trend = bool(row.get("absolute_trend_eligible", True))
    if composite >= config.strong_composite_threshold and is_overheated(row, config):
        return "EXHAUSTED"
    if (
        composite >= config.trending_composite_threshold
        and trend_acceleration < 0
        and rank_change is not None
        and int(rank_change) < 0
    ):
        return "COOLING"
    if (
        rank_change is not None and int(rank_change) > 0 and trend_acceleration > 0
        and acceleration_score >= config.emerging_acceleration_threshold
        and trend_quality_score >= config.emerging_trend_quality_threshold
    ):
        return "EMERGING"
    if (
        composite >= config.strong_composite_threshold
        and trend_quality_score >= config.strong_trend_quality_threshold and absolute_trend
    ):
        return "STRONG"
    if composite >= config.trending_composite_threshold and absolute_trend:
        return "TRENDING"
    if composite < config.weak_composite_threshold or not absolute_trend:
        return "WEAK"
    return "NEUTRAL"


__all__ = ["STATE_PRIORITY", "classify_state", "is_overheated"]

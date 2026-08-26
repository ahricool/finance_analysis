"""Pure momentum and entry score calculations with explanation components."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig


def calculate_momentum_score(
    row: Mapping[str, Any],
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> float:
    score = sum(float(row[f"pct_rank_{window}d"]) * weight for window, weight in config.momentum_weights.items())
    return max(0.0, min(100.0, score))


def ma20_overextension_penalty(value: float, config: ETFRotationConfig = DEFAULT_CONFIG) -> float:
    for threshold, penalty in config.ma20_penalty_thresholds:
        if value >= threshold:
            return penalty
    return 0.0


def calculate_entry_score(
    row: Mapping[str, Any],
    momentum_score: float,
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> tuple[float, dict[str, float]]:
    ret_1d = float(row["ret_1d"])
    acceleration = float(row["momentum_acceleration"])
    rank_change = row.get("rank_change_5d")
    volume_ratio = row.get("volume_ratio_5d")
    components = {
        "base_momentum": float(momentum_score),
        "daily_confirmation": config.daily_confirmation_bonus if 0 < ret_1d <= config.daily_confirmation_max else 0.0,
        "acceleration": (
            config.strong_acceleration_bonus
            if acceleration >= config.strong_acceleration_threshold
            else config.acceleration_bonus if acceleration > 0 else 0.0
        ),
        "rank_improvement": (
            config.rank_improvement_bonus
            if rank_change is not None and int(rank_change) >= config.rank_improvement_threshold
            else 0.0
        ),
        "volume_confirmation": (
            config.volume_confirmation_bonus
            if volume_ratio is not None and float(volume_ratio) >= config.volume_confirmation_threshold
            else 0.0
        ),
        "ma20_penalty": ma20_overextension_penalty(float(row["ma20_ratio"]), config),
        "daily_overheat_penalty": config.daily_overheat_penalty if ret_1d > config.daily_overheat_threshold else 0.0,
    }
    return max(0.0, min(100.0, sum(components.values()))), components


__all__ = ["calculate_entry_score", "calculate_momentum_score", "ma20_overextension_penalty"]

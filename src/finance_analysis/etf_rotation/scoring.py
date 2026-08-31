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


def _weighted(values: list[tuple[float | None, float]]) -> float | None:
    if any(value is None for value, _ in values):
        return None
    return max(0.0, min(100.0, sum(float(value) * weight for value, weight in values if value is not None)))


def map_relative_strength_score(value: float | None, score_range: float) -> float | None:
    """Map absolute excess return to 0..100, with benchmark parity at 50."""
    if value is None:
        return None
    return max(0.0, min(100.0, 50.0 + 50.0 * float(value) / score_range))


def calculate_factor_scores(
    row: Mapping[str, Any], config: ETFRotationConfig = DEFAULT_CONFIG
) -> dict[str, float | None]:
    momentum = calculate_momentum_score(row, config)
    rs_scores = {
        window: map_relative_strength_score(
            row.get(f"rs_{window}d"), config.relative_strength_score_ranges[window]
        )
        for window in config.relative_strength_windows
    }
    relative = _weighted([(rs_scores[window], weight) for window, weight in config.relative_strength_weights.items()])
    acceleration = _weighted([
        (row.get(f"pct_rank_{field}"), weight)
        for field, weight in config.acceleration_weights.items()
    ])
    scores: dict[str, float | None] = {
        "momentum_strength_score": momentum,
        "trend_quality_score": row.get("pct_rank_trend_quality_15d"),
        "relative_strength_score": relative,
        "acceleration_score": acceleration,
        "efficiency_score": row.get("pct_rank_signed_efficiency_ratio_10d"),
        **{f"rs_{window}d_score": value for window, value in rs_scores.items()},
    }
    factor_map = {
        "momentum_strength": scores["momentum_strength_score"],
        "trend_quality": scores["trend_quality_score"],
        "relative_strength": scores["relative_strength_score"],
        "acceleration": scores["acceleration_score"],
        "efficiency": scores["efficiency_score"],
    }
    if factor_map["relative_strength"] is None and not config.allow_missing_relative_strength:
        composite = None
    else:
        available = {key: value for key, value in factor_map.items() if value is not None}
        total_weight = sum(config.factor_weights[key] for key in available)
        composite = (
            sum(float(value) * config.factor_weights[key] for key, value in available.items()) / total_weight
            if total_weight else None
        )
    scores["composite_score"] = None if composite is None else max(0.0, min(100.0, composite))
    return scores


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
    volume_ratio = row.get("volume_ratio_5d")
    components = {
        "base_composite": float(momentum_score),
        "daily_confirmation": config.daily_confirmation_bonus if 0 < ret_1d <= config.daily_confirmation_max else 0.0,
        "volume_confirmation": (
            config.volume_confirmation_bonus
            if volume_ratio is not None and float(volume_ratio) >= config.volume_confirmation_threshold
            else 0.0
        ),
        "ma20_penalty": ma20_overextension_penalty(float(row["ma20_ratio"]), config),
        "daily_overheat_penalty": config.daily_overheat_penalty if ret_1d > config.daily_overheat_threshold else 0.0,
    }
    return max(0.0, min(100.0, sum(components.values()))), components


__all__ = [
    "calculate_entry_score",
    "calculate_factor_scores",
    "calculate_momentum_score",
    "ma20_overextension_penalty",
    "map_relative_strength_score",
]

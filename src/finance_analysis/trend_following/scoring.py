"""Independent score construction for Trend Following."""

from __future__ import annotations

from typing import Any

from finance_analysis.trend_following.config import DEFAULT_CONFIG, TrendFollowingConfig


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _return_quality(value: float) -> float:
    return clamp(50.0 + value * 250.0)


def calculate_trend_score(row: dict[str, Any], config: TrendFollowingConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    components = {
        "weighted_slope_percentile": clamp(row["weighted_slope_percentile"]),
        "weighted_r2": clamp(row["weighted_r2"] * 100.0),
        "return_10d": _return_quality(row["return_10d"]),
        "return_20d": _return_quality(row["return_20d"]),
        "drawdown_quality": clamp(100.0 + row["drawdown_20d"] * 250.0),
    }
    score = sum(components[key] * weight for key, weight in config.trend_score_weights.items())
    return round(clamp(score), 4), components


def calculate_rs_score(row: dict[str, Any], config: TrendFollowingConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    components = {
        "rs_5d": clamp(50.0 + row["rs_5d"] * 400.0),
        "rs_10d": clamp(50.0 + row["rs_10d"] * 350.0),
        "rs_20d": clamp(50.0 + row["rs_20d"] * 300.0),
        "percentile_10d": clamp(row["return_10d_percentile"]),
        "percentile_20d": clamp(row["return_20d_percentile"]),
    }
    score = sum(components[key] * weight for key, weight in config.rs_score_weights.items())
    return round(clamp(score), 4), components


def calculate_breakout_score(row: dict[str, Any]) -> tuple[float, dict]:
    distance_atr = row["breakout_distance"] * row["reference_price"] / max(row["atr20"], 1e-12)
    distance_quality = clamp(100.0 - abs(distance_atr - 0.75) * 55.0) if row["valid_setup"] else 0.0
    extension = max(0.0, row["distance_from_ma20"])
    extension_quality = clamp(100.0 - max(0.0, extension - 0.08) * 800.0)
    volume_quality = clamp((row["volume_ratio"] - 0.5) * 80.0)
    components = {
        "breakout_distance": distance_quality,
        "volume": volume_quality,
        "ma20_extension": extension_quality,
        "compression": 100.0 if row["prior_compression"] else 0.0,
        "breakout_10d": clamp(row["breakout_10d_strength"] * 50.0),
        "breakout_20d": clamp(row["breakout_20d_strength"] * 50.0),
        "trend_resume": 100.0 if row["trend_resume"] else 0.0,
    }
    score = (
        components["breakout_distance"] * 0.25
        + components["volume"] * 0.20
        + components["ma20_extension"] * 0.20
        + components["compression"] * 0.10
        + components["breakout_10d"] * 0.10
        + components["breakout_20d"] * 0.10
        + components["trend_resume"] * 0.05
    )
    return round(clamp(score), 4), components


def calculate_alpha_score(row: dict[str, Any], config: TrendFollowingConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    components = {
        "trend": row["trend_score"],
        "rs": row["rs_score"],
        "breakout": row["breakout_score"],
        "volume": clamp((row["volume_ratio"] - 0.5) * 80.0),
        "compression": 100.0 if row["prior_compression"] else 0.0,
    }
    score = sum(components[key] * weight for key, weight in config.alpha_score_weights.items())
    return round(clamp(score), 4), components


__all__ = ["calculate_alpha_score", "calculate_breakout_score", "calculate_rs_score", "calculate_trend_score"]

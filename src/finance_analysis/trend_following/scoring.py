"""Continuous Alpha V2 scores. State/explanation booleans never award points."""

from __future__ import annotations

import math
from typing import Any

from finance_analysis.trend_following.config import DEFAULT_CONFIG, TrendFollowingConfig


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def sigmoid(value: float) -> float:
    """Stable logistic function, including very large negative inputs."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def smoothstep(value: float, low: float, high: float) -> float:
    t = clamp((value - low) / (high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def tanh_quality(value: float, scale: float) -> float:
    return 50.0 + 50.0 * math.tanh(value / scale)


def gaussian(value: float, center: float, width: float) -> float:
    return math.exp(-0.5 * ((value - center) / width) ** 2)


def _weighted(components: dict, weights: dict[str, float]) -> float:
    return sum(components[key] * weight for key, weight in weights.items())


def calculate_trend_score(row: dict[str, Any], config: TrendFollowingConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    components = {
        "weighted_slope_percentile": clamp(row["weighted_slope_percentile"]),
        "weighted_r2": clamp(row["weighted_r2"] * 100.0),
        **{key: tanh_quality(row[key], scale) for key, scale in config.return_scales.items()},
        "drawdown_quality": 100.0 * math.exp(-abs(row["drawdown_20d"]) / config.drawdown_scale),
    }
    components["momentum"] = _weighted(components, config.momentum_weights)
    score = _weighted(components, config.trend_score_weights)
    return round(score, 4), {
        **components,
        "raw_weighted_r2": row["weighted_r2"],
        "raw_return_10d": row["return_10d"],
        "raw_return_20d": row["return_20d"],
        "drawdown_20d": row["drawdown_20d"],
        "weights": config.trend_score_weights,
        "momentum_weights": config.momentum_weights,
        "score": score,
    }


def calculate_rs_score(row: dict[str, Any], config: TrendFollowingConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    qualities = {key: tanh_quality(row[key], scale) for key, scale in config.rs_scales.items()}
    score = _weighted(qualities, config.rs_score_weights)
    return round(score, 4), {
        "raw": {key: row[key] for key in qualities},
        "qualities": qualities,
        "weights": config.rs_score_weights,
        "score": score,
    }


def breakout_quality(z: float, config: TrendFollowingConfig = DEFAULT_CONFIG) -> float:
    return (
        100.0
        * sigmoid(z / config.breakout_gate_scale)
        * gaussian(z, config.breakout_center_atr, config.breakout_width_atr)
    )


def extension_quality(extension: float, config: TrendFollowingConfig = DEFAULT_CONFIG) -> float:
    return (
        100.0
        * sigmoid((extension - config.extension_gate_center) / config.extension_gate_scale)
        * gaussian(max(0.0, extension - config.extension_penalty_start), 0.0, config.extension_penalty_width)
    )


def calculate_breakout_score(row: dict[str, Any], config: TrendFollowingConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    """Setup score; keep the function/column name as a backwards compatible alias."""
    atr = row["atr20"]
    z10 = (row["reference_price"] - row["previous_high_10"]) / atr if atr > 0 else None
    z20 = (row["reference_price"] - row["previous_high_20"]) / atr if atr > 0 else None
    atr_ratio, range_ratio = row.get("atr_contraction_ratio"), row.get("range_contraction_ratio")
    atr_quality = (
        tanh_quality(config.atr_compression_center - atr_ratio, config.atr_compression_scale)
        if atr_ratio is not None
        else 0.0
    )
    range_quality = (
        tanh_quality(config.range_compression_center - range_ratio, config.range_compression_scale)
        if range_ratio is not None
        else 0.0
    )
    components = {
        "breakout_quality": (
            max(config.breakout_10d_discount * breakout_quality(z10, config), breakout_quality(z20, config))
            if atr > 0
            else 0.0
        ),
        "extension_quality": extension_quality(row["distance_from_ma20"], config),
        "volume_quality": tanh_quality(row["volume_ratio"] - config.volume_center, config.volume_scale),
        "compression_quality": math.sqrt(atr_quality * range_quality),
    }
    score = _weighted(components, config.setup_score_weights)
    return round(score, 4), {
        **components,
        "z10": z10,
        "z20": z20,
        "ma20_extension": row["distance_from_ma20"],
        "volume_ratio": row["volume_ratio"],
        "atr_contraction_ratio": atr_ratio,
        "range_contraction_ratio": range_ratio,
        "atr_compression_quality": atr_quality,
        "range_compression_quality": range_quality,
        "weights": config.setup_score_weights,
        "score": score,
    }


def calculate_path_score(row: dict[str, Any], config: TrendFollowingConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    concentration = row.get("positive_return_concentration")
    expansion = row.get("atr_expansion_ratio")
    downside = row.get("downside_upside_ratio")
    components = {
        "concentration_quality": (
            100.0
            * (1.0 - smoothstep(concentration, config.concentration_high_quality, config.concentration_low_quality))
            if concentration is not None
            else 0.0
        ),
        "volatility_quality": (
            100.0
            * gaussian(max(0.0, expansion - config.volatility_penalty_start), 0.0, config.volatility_penalty_width)
            if expansion is not None
            else 0.0
        ),
        "downside_control_quality": (
            100.0 * math.exp(-downside / config.downside_ratio_scale) if downside is not None else 0.0
        ),
    }
    score = _weighted(components, config.path_score_weights)
    return round(score, 4), {
        **components,
        "positive_return_concentration": concentration,
        "atr_expansion_ratio": expansion,
        "atr5": row.get("atr5"),
        "atr20": row["atr20"],
        "downside_upside_ratio": downside,
        "avg_positive_return": row.get("avg_positive_return"),
        "avg_negative_return_abs": row.get("avg_negative_return_abs"),
        "weights": config.path_score_weights,
        "score": score,
    }


def calculate_alpha_score(row: dict[str, Any], config: TrendFollowingConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    components = {key: row[f"{key}_score"] for key in config.alpha_score_weights}
    contributions = {key: value * config.alpha_score_weights[key] for key, value in components.items()}
    score = sum(contributions.values())
    return round(score, 4), {
        "version": 2,
        "components": components,
        "weights": config.alpha_score_weights,
        "contributions": contributions,
        "score": score,
    }

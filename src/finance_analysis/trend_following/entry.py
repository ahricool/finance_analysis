"""Entry timing research, evaluated after Alpha ranking and fragility."""

from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .scoring import clamp, extension_quality, gaussian, tanh_quality


def calculate_entry(row: dict, config: TrendFollowingConfig = DEFAULT_CONFIG) -> dict:
    setup = row["score_breakdown"]["setup"]
    fragility = row.get("fragility_score")
    clv = row.get("close_location_value")
    extension = row["distance_from_ma20"]
    breakout = any(row.get(key, False) for key in ("breakout_10d", "breakout_20d", "compression_breakout"))
    common = {
        "rs_score": row["rs_score"] >= config.entry_rs_min,
        "alpha_score": row["alpha_score"] >= config.entry_alpha_min,
        "path_score": row["path_score"] >= config.entry_path_min,
        "ma20_rising": row["ma20_slope"] > 0,
        "rs10_positive": row["rs_10d"] > 0,
        "fragility": fragility is None or fragility < config.entry_fragility_max,
    }
    breakout_checks = {
        **common,
        "breakout": breakout,
        "trend_score": row["trend_score"] >= config.entry_trend_min,
        "extension": config.entry_extension_min <= extension <= config.entry_extension_max,
        "clv": clv is not None and clv >= config.entry_clv_min,
    }
    resume_checks = {
        **common,
        "resume": bool(row.get("trend_resume")) and not breakout,
        "trend_score": row["trend_score"] >= config.entry_resume_trend_min,
        "structure": row["reference_price"] > row["ma10"] > row["ma20"],
        "extension": 0 < extension <= config.entry_resume_extension_max,
    }
    shared = {
        "clv": None if clv is None else clamp(clv * 100),
        "rs": tanh_quality(row["rs_10d"], config.rs_scales["rs_10d"]),
        "fragility": None if fragility is None else clamp(100 - fragility),
    }
    breakout_components = {
        **shared,
        "breakout": setup["breakout_quality"],
        "extension": extension_quality(extension, config),
        "volume": (
            None if row.get("volume_provisional") and row.get("projected_volume_ratio") is None
            else setup["volume_quality"]
        ),
        "path": row["path_score"],
    }
    reclaim, depth = row.get("reclaim_distance_atr"), row.get("pullback_depth_atr")
    resume_components = {
        **shared,
        "reclaim": None if reclaim is None else 100 * gaussian(
            reclaim, config.entry_reclaim_center_atr, config.entry_reclaim_width_atr),
        "pullback_depth": None if depth is None else 100 * gaussian(
            depth, config.entry_pullback_center_atr, config.entry_pullback_width_atr),
        "distance": 100 * gaussian(extension, config.entry_resume_distance_center, config.entry_resume_distance_width),
    }

    def evaluate(components, weights, checks):
        available = sum(weights[key] for key, value in components.items() if value is not None)
        normalized = {key: weights[key] / available for key, value in components.items() if value is not None}
        contributions = {key: components[key] * weight for key, weight in normalized.items()}
        quality = sum(contributions.values())
        return {
            "components": components,
            "weights": weights,
            "normalized_weights": normalized,
            "contributions": contributions,
            "checks": checks,
            "quality_score": quality,
            "score": round(quality, 4) if all(checks.values()) else 0.0,
        }

    breakout_result = evaluate(breakout_components, config.breakout_entry_weights, breakout_checks)
    resume_result = evaluate(resume_components, config.resume_entry_weights, resume_checks)
    if all(breakout_checks.values()):
        kind, score = "BREAKOUT", breakout_result["score"]
    elif all(resume_checks.values()):
        kind, score = "PULLBACK_RESUME", resume_result["score"]
    else:
        kind, score = "NONE", 0.0
    return {
        "entry_score": score,
        "entry_type": kind,
        "entry_breakdown": {
            "breakout": breakout_result,
            "resume": resume_result,
            "volume_provisional": row.get("volume_provisional", False),
            "parameters": {key: value for key, value in vars(config).items() if key.startswith("entry_")},
        },
    }

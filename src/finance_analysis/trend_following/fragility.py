"""Deterioration relative to official snapshots; never inverse trend strength."""

from math import isfinite
from statistics import mean
from .health_config import DEFAULT_CONFIG


def number(value):
    return float(value) if isinstance(value, (int, float)) and isfinite(value) else None


def clamp(value):
    return max(0.0, min(100.0, value))


def calculate_fragility(current, history, *, as_of, config=DEFAULT_CONFIG):
    """History is a market-date offset map, batch-loaded once for all symbols.

    Only 3D/5D official baselines are used. Old snapshots without the versioned
    health features are not interpreted as observations of the new definition.
    """
    features = current.get("features") or {}
    fields = {
        "acceleration_decay": "trend_acceleration",
        "quality_decay": "trend_quality",
        "efficiency_decay": "signed_efficiency_ratio_10d",
        "relative_strength_decay": "rs_5d",
        "rank_decay": "rank_percentile",
    }
    components = {}
    for component, field in fields.items():
        now = number(features.get(field))
        values = []
        for offset in (3, 5):
            old = history.get(offset)
            if old is None or old["trade_date"] >= as_of:
                continue
            previous_features = old.get("features") or {}
            if previous_features.get("health_version") != 1:
                continue
            before = number(previous_features.get(field))
            if now is not None and before is not None:
                # Rank percentile increases as the rank worsens; other fields decrease.
                delta = now - before if component == "rank_decay" else before - now
                values.append(clamp(delta / config.decay_scales[component] * 100))
        components[component] = mean(values) if values else None
    distance = number(features.get("distance_from_recent_high"))
    ma_distance = number(features.get("distance_from_ma20"))
    components["price_structure_risk"] = (
        None
        if distance is None or ma_distance is None
        else clamp(max(-distance / config.price_drawdown_scale, -ma_distance / config.price_ma_scale) * 100)
    )
    weight = sum(config.weights[k] for k, v in components.items() if v is not None)
    score = (
        None
        if weight < config.minimum_weight
        else round(sum(config.weights[k] * v for k, v in components.items() if v is not None) / weight, 2)
    )
    return {"fragility_score": score, "fragility_breakdown": components}

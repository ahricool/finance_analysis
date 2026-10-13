"""Descriptive stages layered on existing trend_candidate semantics."""

from .health_config import DEFAULT_CONFIG


def classify_lifecycle(snapshot, config=DEFAULT_CONFIG):
    features = snapshot.get("features") or {}
    scale = features.get("trend_period", 20) / 20
    candidate = features.get("trend_candidate")
    if candidate is None:
        return None
    if not candidate:
        return "BROKEN"
    duration = snapshot.get("trend_duration_days")
    if duration is None:
        return None
    quality = features["weighted_r2"] * 100
    acceleration = features["trend_acceleration"]
    efficiency = features["signed_efficiency_ratio_10d"]
    relative_strength = features.get("rs_5d", 0)
    breakdown = snapshot.get("fragility_breakdown") or {}
    decays = sum(v is not None and v >= config.exhaustion_decay for v in breakdown.values())
    if decays >= config.exhaustion_components:
        return "EXHAUSTION"
    healthy = quality >= config.healthy_quality and efficiency > 0 and features["distance_from_ma20"] > 0
    if duration <= (config.ignition_days * scale) and acceleration > 0 and quality >= config.ignition_quality:
        return "IGNITION"
    if duration <= (config.emerging_days * scale):
        return "EMERGING"
    if duration >= (config.mature_days * scale):
        return "MATURE"
    if (
        duration > (config.emerging_days * scale)
        and quality >= config.expansion_quality
        and efficiency >= config.expansion_efficiency
        and relative_strength >= config.expansion_rs
        and acceleration >= config.stable_acceleration
        and healthy
    ):
        return "EXPANSION"
    # Past early formation, an intact non-expanding trend is established, not emerging.
    # MATURE describes lifecycle, not strength or a trading recommendation.
    return "MATURE"

"""Descriptive stages layered on existing trend_candidate semantics."""

from .health_config import DEFAULT_CONFIG


def classify_lifecycle(snapshot, config=DEFAULT_CONFIG):
    features = snapshot.get("features") or {}
    candidate = features.get("trend_candidate")
    if candidate is None:
        return None
    if not candidate:
        return "BROKEN"
    duration = snapshot.get("trend_duration_days")
    if duration is None:
        return None
    quality = features["trend_quality"]
    acceleration = features["trend_acceleration"]
    efficiency = features["signed_efficiency_ratio_10d"]
    relative_strength = features.get("rs_5d", 0)
    breakdown = snapshot.get("fragility_breakdown") or {}
    decays = sum(v is not None and v >= config.exhaustion_decay for v in breakdown.values())
    if decays >= config.exhaustion_components:
        return "EXHAUSTION"
    healthy = quality >= config.healthy_quality and efficiency > 0 and features["distance_from_ma20"] > 0
    if duration <= config.ignition_days and acceleration > 0 and quality >= config.ignition_quality:
        return "IGNITION"
    if duration >= config.mature_days and healthy and acceleration >= config.stable_acceleration:
        return "MATURE"
    if (
        duration > config.emerging_days
        and quality >= config.expansion_quality
        and efficiency >= config.expansion_efficiency
        and relative_strength >= config.expansion_rs
        and acceleration >= config.stable_acceleration
        and healthy
    ):
        return "EXPANSION"
    # A candidate can be tentative or stalled without meeting the exhaustion evidence threshold.
    return "EMERGING"

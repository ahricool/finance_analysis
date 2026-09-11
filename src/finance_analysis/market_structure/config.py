"""Versioned explanatory thresholds; returns and ratios use decimal units."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketStructureConfig:
    version: str = "1"
    minimum_coverage: float = 0.95
    lookback_days: int = 90
    top_fraction: float = 0.10
    mild_divergence: float = 0.01
    strong_divergence: float = 0.025
    broad_positive_ratio: float = 0.70
    rotation_normal: float = 20
    rotation_fast: float = 50
    rotation_extreme: float = 75


DEFAULT_CONFIG = MarketStructureConfig()

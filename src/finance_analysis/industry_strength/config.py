"""Versioned, deterministic industry observation thresholds (decimal returns)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndustryStrengthConfig:
    version: str = "1"
    benchmark: str = "000300.SH"
    minimum_coverage: float = 0.95
    minimum_breadth_coverage: float = 0.95
    lookback_days: int = 100
    weights: tuple = ((5, 0.40), (10, 0.35), (20, 0.25))
    strong_score: float = 75
    strong_top_fraction: float = 0.25
    strong_breadth: float = 0.60
    strong_ma20: float = 0.60
    emerging_rank_gain: int = 5
    emerging_acceleration_percentile: float = 75
    emerging_turnover: float = 1.0
    cooling_score: float = 60
    cooling_rank_loss: int = -3
    cooling_breadth: float = 0.45
    weak_score: float = 25
    weak_breadth: float = 0.40
    weak_ma20: float = 0.40


DEFAULT_CONFIG = IndustryStrengthConfig()

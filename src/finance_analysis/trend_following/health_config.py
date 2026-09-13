"""Analytical lifecycle/fragility configuration, independent of trading rules."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TrendHealthConfig:
    ignition_days: int = 3
    emerging_days: int = 7
    mature_days: int = 20
    ignition_quality: float = 50
    healthy_quality: float = 65
    expansion_quality: float = 80
    expansion_efficiency: float = 0.55
    expansion_rs: float = 0
    stable_acceleration: float = -0.05
    exhaustion_decay: float = 50
    exhaustion_components: int = 2
    price_drawdown_scale: float = 0.10
    price_ma_scale: float = 0.05
    decay_scales: dict = field(
        default_factory=lambda: {
            "acceleration_decay": 0.50,
            "quality_decay": 30.0,
            "efficiency_decay": 0.50,
            "relative_strength_decay": 0.05,
            "rank_decay": 0.25,
        }
    )
    weights: dict = field(
        default_factory=lambda: {
            "acceleration_decay": 0.25,
            "quality_decay": 0.20,
            "efficiency_decay": 0.15,
            "relative_strength_decay": 0.15,
            "rank_decay": 0.15,
            "price_structure_risk": 0.10,
        }
    )
    minimum_weight: float = 0.50
    high_fragility: float = 65


DEFAULT_CONFIG = TrendHealthConfig()

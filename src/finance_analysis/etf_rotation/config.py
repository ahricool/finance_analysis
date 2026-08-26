"""Central configuration for the deterministic V1 strategy."""

from __future__ import annotations

from dataclasses import dataclass, field


RETURN_WINDOWS = (1, 5, 10, 20, 30, 60)


@dataclass(frozen=True)
class ETFRotationConfig:
    momentum_weights: dict[int, float] = field(
        default_factory=lambda: {5: 0.40, 10: 0.25, 30: 0.20, 60: 0.15}
    )
    minimum_data_coverage: float = 0.95
    minimum_rankable_coverage: float = 0.95
    daily_confirmation_max: float = 0.04
    daily_confirmation_bonus: float = 3.0
    strong_acceleration_threshold: float = 0.05
    acceleration_bonus: float = 5.0
    strong_acceleration_bonus: float = 8.0
    rank_improvement_threshold: int = 10
    rank_improvement_bonus: float = 5.0
    volume_confirmation_threshold: float = 1.2
    volume_confirmation_bonus: float = 2.0
    daily_overheat_threshold: float = 0.06
    daily_overheat_penalty: float = -5.0
    ma20_penalty_thresholds: tuple[tuple[float, float], ...] = (
        (0.15, -10.0),
        (0.10, -5.0),
        (0.05, -2.0),
    )
    max_candidates: int = 5
    max_per_risk_group: int = 2
    excluded_candidate_states: frozenset[str] = frozenset({"WEAK", "EXHAUSTED"})
    history_limit_default: int = 60
    history_limit_max: int = 365


DEFAULT_CONFIG = ETFRotationConfig()

__all__ = ["DEFAULT_CONFIG", "ETFRotationConfig", "RETURN_WINDOWS"]

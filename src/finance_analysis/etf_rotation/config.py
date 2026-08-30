"""Central configuration for the deterministic fast ETF rotation strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


RETURN_WINDOWS = (1, 3, 5, 10, 20)


@dataclass(frozen=True)
class ETFRotationConfig:
    momentum_weights: dict[int, float] = field(
        default_factory=lambda: {3: 0.30, 5: 0.35, 10: 0.25, 20: 0.10}
    )
    factor_weights: dict[str, float] = field(default_factory=lambda: {
        "momentum_strength": 0.30, "relative_strength": 0.25, "acceleration": 0.25,
        "trend_quality": 0.15, "efficiency": 0.05,
    })
    benchmark_codes: dict[str, str] = field(default_factory=lambda: {"CN": "510300.SH", "US": "SPY.US"})
    regression_windows: tuple[int, ...] = (5, 10, 15)
    regression_oldest_weight: float = 1.0
    regression_latest_weight: float = 2.0
    annualized_slope_clip: float = 20.0
    efficiency_window: int = 10
    relative_strength_windows: tuple[int, ...] = (5, 10, 20)
    relative_strength_weights: dict[int, float] = field(default_factory=lambda: {5: 0.40, 10: 0.40, 20: 0.20})
    relative_strength_score_ranges: dict[int, float] = field(
        default_factory=lambda: {5: 0.05, 10: 0.08, 20: 0.12}
    )
    acceleration_weights: dict[str, float] = field(
        default_factory=lambda: {
            "momentum_acceleration_3d": 0.40,
            "momentum_acceleration_5d": 0.35,
            "trend_acceleration": 0.25,
        }
    )
    allow_missing_relative_strength: bool = False
    minimum_data_coverage: float = 0.95
    minimum_rankable_coverage: float = 0.95
    daily_confirmation_max: float = 0.04
    daily_confirmation_bonus: float = 2.0
    volume_confirmation_threshold: float = 1.2
    volume_confirmation_bonus: float = 2.0
    daily_overheat_threshold: float = 0.06
    daily_overheat_penalty: float = -5.0
    ma20_penalty_thresholds: tuple[tuple[float, float], ...] = (
        (0.15, -10.0),
        (0.10, -5.0),
        (0.05, -2.0),
    )
    entry_rank_threshold: int = 4
    hold_rank_threshold: int = 6
    entry_score_threshold: float = 70.0
    hold_composite_threshold: float = 60.0
    watch_composite_threshold: float = 55.0
    absolute_trend_min_conditions: int = 2
    minimum_liquidity: dict[str, float] = field(default_factory=lambda: {"CN": 50_000_000.0, "US": 5_000_000.0})
    max_candidates: int = 5
    neutral_max_candidates: int = 3
    risk_off_max_candidates: int = 0
    max_per_risk_group: int = 2
    max_candidate_correlation: float = 0.85
    correlation_window: int = 20
    regime_risk_on_breadth: float = 0.55
    regime_risk_off_breadth: float = 0.30
    stop_vol_multiplier: float = 2.5
    minimum_stop_pct: float = 0.03
    maximum_stop_pct: float = 0.08
    entry_candidate_states: frozenset[str] = frozenset({"EMERGING", "STRONG", "TRENDING"})
    strong_composite_threshold: float = 75.0
    strong_trend_quality_threshold: float = 65.0
    trending_composite_threshold: float = 60.0
    emerging_rank_change_3d: int = 5
    emerging_acceleration_threshold: float = 70.0
    emerging_rs10_threshold: float = 60.0
    cooling_composite_threshold: float = 55.0
    weak_composite_threshold: float = 40.0
    hold_acceleration_threshold: float = 40.0
    exit_acceleration_threshold: float = 35.0
    rank_collapse_threshold: int = -4
    history_limit_default: int = 60
    history_limit_max: int = 365

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not math.isclose(sum(self.momentum_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("momentum_weights must sum to 1")
        if not math.isclose(sum(self.factor_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("factor_weights must sum to 1")
        if not math.isclose(sum(self.relative_strength_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("relative_strength_weights must sum to 1")
        if set(self.relative_strength_score_ranges) != set(self.relative_strength_windows):
            raise ValueError("relative_strength_score_ranges must define every relative strength window")
        if any(value <= 0 for value in self.relative_strength_score_ranges.values()):
            raise ValueError("relative_strength_score_ranges must be positive")
        if not math.isclose(sum(self.acceleration_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("acceleration_weights must sum to 1")
        if self.entry_rank_threshold > self.hold_rank_threshold:
            raise ValueError("entry_rank_threshold must be <= hold_rank_threshold")
        if self.entry_score_threshold < self.hold_composite_threshold:
            raise ValueError("entry_score_threshold must be >= hold_composite_threshold")
        if not 0 <= self.max_candidate_correlation <= 1:
            raise ValueError("max_candidate_correlation must be between 0 and 1")
        if min(self.regression_windows) <= 1:
            raise ValueError("regression windows must be greater than 1")
        if max(self.regression_windows) > max(RETURN_WINDOWS):
            raise ValueError("regression windows exceed the supported history")
        if self.regression_oldest_weight <= 0 or self.regression_latest_weight <= 0:
            raise ValueError("regression weights must be positive")
        if set(self.benchmark_codes) != {"CN", "US"} or not all(self.benchmark_codes.values()):
            raise ValueError("benchmark_codes must define non-empty CN and US benchmarks")
        if set(self.minimum_liquidity) != {"CN", "US"} or any(value < 0 for value in self.minimum_liquidity.values()):
            raise ValueError("minimum_liquidity must define non-negative CN and US thresholds")
        if not 0 <= self.regime_risk_off_breadth < self.regime_risk_on_breadth <= 1:
            raise ValueError("regime breadth thresholds must satisfy 0 <= risk_off < risk_on <= 1")
        if min(self.max_candidates, self.neutral_max_candidates, self.risk_off_max_candidates) < 0:
            raise ValueError("candidate limits must be non-negative")


DEFAULT_CONFIG = ETFRotationConfig()

__all__ = ["DEFAULT_CONFIG", "ETFRotationConfig", "RETURN_WINDOWS"]

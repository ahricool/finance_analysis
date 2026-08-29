"""Central configuration for the deterministic ETF Rotation V2 strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


RETURN_WINDOWS = (1, 5, 10, 20, 30, 60)


@dataclass(frozen=True)
class ETFRotationConfig:
    momentum_weights: dict[int, float] = field(
        default_factory=lambda: {5: 0.10, 20: 0.20, 30: 0.30, 60: 0.40}
    )
    factor_weights: dict[str, float] = field(default_factory=lambda: {
        "momentum_strength": 0.30, "trend_quality": 0.25, "relative_strength": 0.20,
        "acceleration": 0.10, "efficiency": 0.10, "risk_adjusted": 0.05,
    })
    benchmark_codes: dict[str, str] = field(default_factory=lambda: {"CN": "510300.SH", "US": "SPY.US"})
    regression_short_window: int = 10
    regression_long_window: int = 25
    regression_oldest_weight: float = 1.0
    regression_latest_weight: float = 2.0
    annualized_slope_clip: float = 20.0
    efficiency_window: int = 20
    risk_adjusted_window: int = 60
    relative_strength_windows: tuple[int, ...] = (20, 60)
    relative_strength_weights: dict[int, float] = field(default_factory=lambda: {20: 0.40, 60: 0.60})
    acceleration_weights: dict[str, float] = field(
        default_factory=lambda: {"trend_acceleration": 0.75, "momentum_acceleration": 0.25}
    )
    risk_adjusted_weights: dict[str, float] = field(
        default_factory=lambda: {"risk_adjusted_momentum_60d": 0.80, "max_drawdown_60d": 0.20}
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
    entry_rank: int = 5
    hold_rank: int = 10
    entry_score: float = 75.0
    hold_score: float = 60.0
    watch_score: float = 55.0
    absolute_trend_require_positive_slope: bool = True
    absolute_trend_min_secondary_conditions: int = 1
    minimum_liquidity: dict[str, float] = field(default_factory=lambda: {"CN": 50_000_000.0, "US": 5_000_000.0})
    max_candidates: int = 5
    neutral_max_candidates: int = 3
    risk_off_max_candidates: int = 0
    max_per_risk_group: int = 2
    max_candidate_correlation: float = 0.85
    correlation_window: int = 60
    regime_risk_on_breadth_ma60: float = 0.60
    regime_risk_off_breadth_ma60: float = 0.30
    stop_vol_multiplier: float = 2.5
    minimum_stop_pct: float = 0.03
    maximum_stop_pct: float = 0.08
    excluded_candidate_states: frozenset[str] = frozenset({"WEAK", "EXHAUSTED"})
    strong_composite_threshold: float = 80.0
    strong_trend_quality_threshold: float = 70.0
    trending_composite_threshold: float = 60.0
    emerging_acceleration_threshold: float = 55.0
    emerging_trend_quality_threshold: float = 50.0
    weak_composite_threshold: float = 40.0
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
        if not math.isclose(sum(self.acceleration_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("acceleration_weights must sum to 1")
        if not math.isclose(sum(self.risk_adjusted_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("risk_adjusted_weights must sum to 1")
        if self.entry_rank > self.hold_rank:
            raise ValueError("entry_rank must be <= hold_rank")
        if self.entry_score < self.hold_score:
            raise ValueError("entry_score must be >= hold_score")
        if not 0 <= self.max_candidate_correlation <= 1:
            raise ValueError("max_candidate_correlation must be between 0 and 1")
        if min(self.regression_short_window, self.regression_long_window) <= 1:
            raise ValueError("regression windows must be greater than 1")
        if max(self.regression_short_window, self.regression_long_window) > max(RETURN_WINDOWS) + 1:
            raise ValueError("regression windows exceed the supported history")
        if self.regression_oldest_weight <= 0 or self.regression_latest_weight <= 0:
            raise ValueError("regression weights must be positive")
        if set(self.benchmark_codes) != {"CN", "US"} or not all(self.benchmark_codes.values()):
            raise ValueError("benchmark_codes must define non-empty CN and US benchmarks")
        if set(self.minimum_liquidity) != {"CN", "US"} or any(value < 0 for value in self.minimum_liquidity.values()):
            raise ValueError("minimum_liquidity must define non-negative CN and US thresholds")
        if self.risk_adjusted_window != 60:
            raise ValueError("risk_adjusted_window must remain 60 for risk_adjusted_momentum_60d")
        if not 0 <= self.regime_risk_off_breadth_ma60 < self.regime_risk_on_breadth_ma60 <= 1:
            raise ValueError("regime breadth thresholds must satisfy 0 <= risk_off < risk_on <= 1")
        if min(self.max_candidates, self.neutral_max_candidates, self.risk_off_max_candidates) < 0:
            raise ValueError("candidate limits must be non-negative")


DEFAULT_CONFIG = ETFRotationConfig()

__all__ = ["DEFAULT_CONFIG", "ETFRotationConfig", "RETURN_WINDOWS"]

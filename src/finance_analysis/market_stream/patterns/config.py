"""Central configuration for deterministic 1-minute pattern detection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PatternConfig:
    """Thresholds tuned conservatively for liquid symbols while remaining market-neutral."""

    baseline_window: int = 20
    minimum_history_bars: int = 15
    atr_epsilon: Decimal = Decimal("0.00000001")
    vwap_price_tolerance_atr: Decimal = Decimal("0.50")

    level_lookback: int = 10
    breakout_min_atr: Decimal = Decimal("0.15")
    breakout_body_median_ratio: Decimal = Decimal("0.80")
    reclaim_max_bars: int = 3
    reclaim_confirm_atr: Decimal = Decimal("0.08")
    invalidation_tolerance_atr: Decimal = Decimal("0.10")

    retest_max_bars: int = 8
    retest_penetration_atr: Decimal = Decimal("0.25")
    retest_resume_atr: Decimal = Decimal("0.08")
    retest_invalidation_closes: int = 2

    swing_span: int = 1
    double_min_separation: int = 3
    double_max_separation: int = 20
    double_level_tolerance_atr: Decimal = Decimal("0.35")
    double_neckline_min_atr: Decimal = Decimal("0.80")
    double_breakout_atr: Decimal = Decimal("0.08")
    double_invalidation_atr: Decimal = Decimal("0.15")
    double_confirmation_max_bars: int = 8

    impulse_min_bars: int = 2
    impulse_max_bars: int = 6
    impulse_min_atr: Decimal = Decimal("1.20")
    impulse_min_efficiency: Decimal = Decimal("0.65")
    impulse_min_direction_ratio: Decimal = Decimal("0.67")
    impulse_body_median_ratio: Decimal = Decimal("1.30")
    impulse_max_overlap: Decimal = Decimal("0.45")
    pullback_min_bars: int = 2
    pullback_max_bars: int = 8
    pullback_min_retracement: Decimal = Decimal("0.20")
    pullback_max_retracement: Decimal = Decimal("0.65")
    pullback_body_ratio: Decimal = Decimal("0.70")
    pullback_range_ratio: Decimal = Decimal("0.80")
    pullback_min_overlap: Decimal = Decimal("0.50")
    pullback_resume_atr: Decimal = Decimal("0.05")
    pullback_volume_bonus: int = 3

    compression_min_bars: int = 4
    compression_max_bars: int = 8
    compression_reference_bars: int = 8
    compression_range_ratio: Decimal = Decimal("0.70")
    compression_width_atr: Decimal = Decimal("1.50")
    compression_min_overlap: Decimal = Decimal("0.55")
    compression_body_ratio: Decimal = Decimal("0.70")
    compression_breakout_body_ratio: Decimal = Decimal("1.40")
    compression_hold_bars: int = 1
    compression_failure_bars: int = 2
    compression_volume_bonus: int = 3

    vwap_prior_bars: int = 8
    vwap_prior_side_ratio: Decimal = Decimal("0.65")
    vwap_cross_atr: Decimal = Decimal("0.10")
    vwap_retest_max_bars: int = 6
    vwap_retest_tolerance_atr: Decimal = Decimal("0.20")
    vwap_resume_atr: Decimal = Decimal("0.05")
    vwap_invalidation_closes: int = 2

    current_age_bars: int = 3
    recent_age_bars: int = 8
    maximum_age_bars: int = 15
    recent_age_penalty: int = 8
    historical_age_penalty: int = 18
    confirmed_score_bonus: int = 12
    warning_score_bonus: int = 5
    volume_score_bonus: int = 6
    high_volume_ratio: Decimal = Decimal("1.20")
    strong_structure_bonus: int = 8
    structure_score_per_atr: Decimal = Decimal("4")
    missing_volume_penalty: int = 2
    failed_breakout_base_score: int = 64
    breakout_retest_base_score: int = 60
    double_pattern_base_score: int = 62
    impulse_pullback_base_score: int = 58
    compression_base_score: int = 55
    vwap_base_score: int = 58

    def __post_init__(self) -> None:
        if self.minimum_history_bars < 2 or self.baseline_window < self.minimum_history_bars:
            raise ValueError("pattern history must satisfy 2 <= minimum_history_bars <= baseline_window")
        if not (0 <= self.current_age_bars <= self.recent_age_bars <= self.maximum_age_bars):
            raise ValueError("pattern age thresholds must be ordered")
        if self.reclaim_max_bars < 1 or self.retest_max_bars < 1 or self.vwap_retest_max_bars < 1:
            raise ValueError("pattern follow-through windows must be positive")

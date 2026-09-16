"""Central configuration for the trend-following strategy."""

from __future__ import annotations

from dataclasses import dataclass, field

TREND_UNIVERSE_KEYS = {"CN": "cn_trend", "US": "us_trend"}


@dataclass(frozen=True)
class TrendFollowingConfig:
    history_bars: int = 60
    minimum_history_bars: int = 21
    calendar_lookback_days: int = 180
    minimum_data_coverage: float = 0.90
    benchmark_codes: dict[str, str] = field(default_factory=lambda: {"CN": "510300.SH", "US": "SPY.US"})
    universe_keys: dict[str, str] = field(default_factory=lambda: dict(TREND_UNIVERSE_KEYS))
    risk_on_threshold: float = 65.0
    risk_off_threshold: float = 40.0
    regime_weights: dict[str, float] = field(default_factory=lambda: {"trend": 0.35, "breadth": 0.40, "risk": 0.25})
    # Alpha V2 weights and curve scales; returns use decimal units.
    trend_score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "weighted_slope_percentile": 0.30,
            "weighted_r2": 0.30,
            "momentum": 0.25,
            "drawdown_quality": 0.15,
        }
    )
    momentum_weights: dict[str, float] = field(default_factory=lambda: {"return_10d": 0.6, "return_20d": 0.4})
    return_scales: dict[str, float] = field(default_factory=lambda: {"return_10d": 0.12, "return_20d": 0.18})
    rs_score_weights: dict[str, float] = field(default_factory=lambda: {"rs_5d": 0.25, "rs_10d": 0.45, "rs_20d": 0.30})
    rs_scales: dict[str, float] = field(default_factory=lambda: {"rs_5d": 0.08, "rs_10d": 0.12, "rs_20d": 0.18})
    setup_score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "breakout_quality": 0.50,
            "extension_quality": 0.25,
            "volume_quality": 0.15,
            "compression_quality": 0.10,
        }
    )
    path_score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "concentration_quality": 0.45,
            "volatility_quality": 0.35,
            "downside_control_quality": 0.20,
        }
    )
    alpha_score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "trend": 0.40,
            "rs": 0.25,
            "setup": 0.15,
            "path": 0.20,
        }
    )
    drawdown_scale: float = 0.15
    breakout_gate_scale: float = 0.15
    breakout_center_atr: float = 0.75
    breakout_width_atr: float = 1.0
    breakout_10d_discount: float = 0.85
    extension_gate_center: float = 0.015
    extension_gate_scale: float = 0.01
    extension_penalty_start: float = 0.08
    extension_penalty_width: float = 0.12
    volume_center: float = 1.0
    volume_scale: float = 0.8
    atr_compression_center: float = 0.90
    atr_compression_scale: float = 0.15
    range_compression_center: float = 0.70
    range_compression_scale: float = 0.20
    concentration_high_quality: float = 0.45
    concentration_low_quality: float = 0.80
    volatility_penalty_start: float = 1.10
    volatility_penalty_width: float = 0.80
    downside_ratio_scale: float = 1.0
    path_return_window: int = 10
    concentration_top_count: int = 2
    volatility_atr_window: int = 5
    compare_alpha_v1: bool = False  # Debug only; remove with scoring_v1.py after V2 validation.
    candidate_trend_score: float = 62.0
    candidate_rs_score: float = 60.0
    candidate_alpha_score: float = 67.0
    healthy_trend_score: float = 60.0
    healthy_rs_score: float = 55.0
    history_limit_default: int = 60
    history_limit_max: int = 250


DEFAULT_CONFIG = TrendFollowingConfig()

__all__ = ["DEFAULT_CONFIG", "TREND_UNIVERSE_KEYS", "TrendFollowingConfig"]

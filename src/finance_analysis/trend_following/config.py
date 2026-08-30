"""Central configuration for the trend-following strategy."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TrendFollowingConfig:
    history_bars: int = 120
    minimum_history_bars: int = 61
    calendar_lookback_days: int = 220
    minimum_data_coverage: float = 0.95
    benchmark_codes: dict[str, str] = field(
        default_factory=lambda: {"CN": "510300.SH", "US": "SPY.US"}
    )
    universe_keys: dict[str, str] = field(
        default_factory=lambda: {"CN": "cn_csi300_csi500", "US": "us_sp500"}
    )
    risk_on_threshold: float = 65.0
    risk_off_threshold: float = 40.0
    regime_max_exposure: dict[str, float] = field(
        default_factory=lambda: {"RISK_ON": 1.0, "NEUTRAL": 0.5, "RISK_OFF": 0.0}
    )
    regime_weights: dict[str, float] = field(
        default_factory=lambda: {"trend": 0.35, "breadth": 0.40, "risk": 0.25}
    )
    trend_score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "weighted_slope_percentile": 0.30,
            "weighted_r2": 0.25,
            "return_20d": 0.20,
            "return_60d": 0.15,
            "drawdown_quality": 0.10,
        }
    )
    rs_score_weights: dict[str, float] = field(
        default_factory=lambda: {"rs_20d": 0.30, "rs_60d": 0.20, "percentile_20d": 0.30, "percentile_60d": 0.20}
    )
    alpha_score_weights: dict[str, float] = field(
        default_factory=lambda: {"trend": 0.35, "rs": 0.30, "breakout": 0.20, "volume": 0.10, "compression": 0.05}
    )
    candidate_trend_score: float = 65.0
    candidate_rs_score: float = 65.0
    candidate_alpha_score: float = 70.0
    add_trend_score: float = 60.0
    add_rs_score: float = 55.0
    reduce_rs_score: float = 55.0
    risk_per_trade: float = 0.005
    single_stock_max_weight: float = 0.10
    max_units: int = 4
    initial_stop_atr: float = 2.0
    structure_stop_buffer_atr: float = 0.5
    pyramid_interval_atr: float = 0.5
    trailing_stop_atr: float = 2.5
    candidate_expiry_sessions: int = 1
    history_limit_default: int = 60
    history_limit_max: int = 250


DEFAULT_CONFIG = TrendFollowingConfig()

__all__ = ["DEFAULT_CONFIG", "TrendFollowingConfig"]

"""Central configuration for the trend-following strategy."""

from __future__ import annotations

from dataclasses import dataclass, field

TREND_UNIVERSE_KEYS = {"CN": "cn_trend", "US": "us_trend"}


@dataclass(frozen=True)
class TrendFollowingConfig:
    history_bars: int = 60
    minimum_history_bars: int = 21
    calendar_lookback_days: int = 180
    minimum_data_coverage: float = 0.95
    benchmark_codes: dict[str, str] = field(
        default_factory=lambda: {"CN": "510300.SH", "US": "SPY.US"}
    )
    universe_keys: dict[str, str] = field(
        default_factory=lambda: dict(TREND_UNIVERSE_KEYS)
    )
    risk_on_threshold: float = 65.0
    risk_off_threshold: float = 40.0
    regime_max_exposure: dict[str, float] = field(
        default_factory=lambda: {"RISK_ON": 1.0, "NEUTRAL": 0.5, "RISK_OFF": 0.2}
    )
    regime_weights: dict[str, float] = field(
        default_factory=lambda: {"trend": 0.35, "breadth": 0.40, "risk": 0.25}
    )
    trend_score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "weighted_slope_percentile": 0.30,
            "weighted_r2": 0.20,
            "return_10d": 0.20,
            "return_20d": 0.20,
            "drawdown_quality": 0.10,
        }
    )
    rs_score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "rs_5d": 0.25,
            "rs_10d": 0.35,
            "rs_20d": 0.20,
            "percentile_10d": 0.10,
            "percentile_20d": 0.10,
        }
    )
    alpha_score_weights: dict[str, float] = field(
        default_factory=lambda: {"trend": 0.35, "rs": 0.30, "breakout": 0.20, "volume": 0.10, "compression": 0.05}
    )
    candidate_trend_score: float = 62.0
    candidate_rs_score: float = 60.0
    candidate_alpha_score: float = 67.0
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

    def __post_init__(self) -> None:
        if self.candidate_expiry_sessions != 1:
            raise ValueError("Trend Following currently supports candidate_expiry_sessions=1 only")


DEFAULT_CONFIG = TrendFollowingConfig()

__all__ = ["DEFAULT_CONFIG", "TREND_UNIVERSE_KEYS", "TrendFollowingConfig"]

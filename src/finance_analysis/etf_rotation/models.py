"""Small transport types used by the pure calculation engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    close: float
    volume: float
    amount: float | None = None


@dataclass(frozen=True)
class FeatureSet:
    reference_price: float
    ret_1d: float
    ret_3d: float
    ret_5d: float
    ret_10d: float
    ret_20d: float
    previous_3d_return: float
    previous_5d_return: float
    momentum_acceleration_3d: float
    momentum_acceleration_5d: float
    ma10_ratio: float
    ma20_ratio: float
    volume_ratio_5d: float | None
    avg_amount_20d: float | None
    realized_vol_20d: float
    distance_from_20d_high: float
    weighted_slope_5d: float
    weighted_slope_10d: float
    weighted_slope_15d: float
    annualized_slope_5d: float
    annualized_slope_10d: float
    annualized_slope_15d: float
    trend_r2_15d: float
    trend_quality_15d: float
    signed_efficiency_ratio_10d: float
    trend_acceleration: float
    max_drawdown_20d: float

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


__all__ = ["DailyBar", "FeatureSet"]

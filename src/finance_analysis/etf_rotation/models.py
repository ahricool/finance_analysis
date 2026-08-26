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
    ret_5d: float
    ret_10d: float
    ret_20d: float
    ret_30d: float
    ret_60d: float
    previous_5d_return: float
    momentum_acceleration: float
    ma20_ratio: float
    ma60_ratio: float
    volume_ratio_5d: float | None
    avg_amount_20d: float | None
    realized_vol_20d: float
    distance_from_20d_high: float

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


__all__ = ["DailyBar", "FeatureSet"]

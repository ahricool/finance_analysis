"""Pure point-in-time ETF feature calculations over PostgreSQL daily bars."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from finance_analysis.etf_rotation.config import RETURN_WINDOWS
from finance_analysis.etf_rotation.models import DailyBar, FeatureSet

MINIMUM_HISTORY_BARS = max(RETURN_WINDOWS) + 1


def calculate_features(bars: Sequence[DailyBar]) -> FeatureSet | None:
    """Calculate V1 features from bars ordered oldest to newest.

    The current close is only compared with current or earlier sessions.  A
    minimum of 61 bars is required so every configured return is rankable.
    """
    if len(bars) < MINIMUM_HISTORY_BARS:
        return None
    ordered = sorted(bars, key=lambda item: item.trade_date)
    closes = [float(item.close) for item in ordered]
    if any(value <= 0 or not math.isfinite(value) for value in closes[-MINIMUM_HISTORY_BARS:]):
        return None
    current = closes[-1]
    returns = {window: current / closes[-1 - window] - 1.0 for window in RETURN_WINDOWS}
    previous_5d = closes[-6] / closes[-11] - 1.0
    ma20 = statistics.fmean(closes[-20:])
    ma60 = statistics.fmean(closes[-60:])
    daily_returns = [closes[index] / closes[index - 1] - 1.0 for index in range(len(closes) - 20, len(closes))]
    realized_vol = statistics.stdev(daily_returns) * math.sqrt(252) if len(daily_returns) > 1 else 0.0
    volumes = [max(0.0, float(item.volume)) for item in ordered[-20:]]
    average_volume_20d = statistics.fmean(volumes)
    volume_ratio = statistics.fmean(volumes[-5:]) / average_volume_20d if average_volume_20d > 0 else None
    amounts = [float(item.amount) for item in ordered[-20:] if item.amount is not None]
    average_amount = statistics.fmean(amounts) if amounts else None
    return FeatureSet(
        reference_price=current,
        **{f"ret_{window}d": returns[window] for window in RETURN_WINDOWS},
        previous_5d_return=previous_5d,
        momentum_acceleration=returns[5] - previous_5d,
        ma20_ratio=current / ma20 - 1.0,
        ma60_ratio=current / ma60 - 1.0,
        volume_ratio_5d=volume_ratio,
        avg_amount_20d=average_amount,
        realized_vol_20d=realized_vol,
        distance_from_20d_high=current / max(closes[-20:]) - 1.0,
    )


__all__ = ["MINIMUM_HISTORY_BARS", "calculate_features"]

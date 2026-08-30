"""Pure point-in-time ETF feature calculations over PostgreSQL daily bars."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, RETURN_WINDOWS, ETFRotationConfig
from finance_analysis.etf_rotation.models import DailyBar, FeatureSet

MINIMUM_HISTORY_BARS = max(RETURN_WINDOWS) + 1


def _weighted_log_regression(
    closes: Sequence[float], oldest_weight: float, latest_weight: float
) -> tuple[float, float]:
    """Return weighted log-price slope and the matching weighted R-squared."""
    count = len(closes)
    x = [float(index) for index in range(count)]
    y = [math.log(value) for value in closes]
    weights = [oldest_weight + (latest_weight - oldest_weight) * index / (count - 1) for index in range(count)]
    weight_sum = sum(weights)
    mean_x = sum(weight * value for weight, value in zip(weights, x)) / weight_sum
    mean_y = sum(weight * value for weight, value in zip(weights, y)) / weight_sum
    denominator = sum(weight * (value - mean_x) ** 2 for weight, value in zip(weights, x))
    slope = sum(weight * (xv - mean_x) * (yv - mean_y) for weight, xv, yv in zip(weights, x, y)) / denominator
    intercept = mean_y - slope * mean_x
    residual = sum(weight * (yv - (intercept + slope * xv)) ** 2 for weight, xv, yv in zip(weights, x, y))
    total = sum(weight * (yv - mean_y) ** 2 for weight, yv in zip(weights, y))
    r_squared = 1.0 if total <= 1e-24 else max(0.0, min(1.0, 1.0 - residual / total))
    return slope, r_squared


def _annualize_slope(slope: float, clip: float) -> float:
    exponent = max(-clip, min(clip, slope * 252.0))
    return math.expm1(exponent)


def _maximum_drawdown(closes: Sequence[float]) -> float:
    peak = closes[0]
    maximum = 0.0
    for close in closes:
        peak = max(peak, close)
        maximum = min(maximum, close / peak - 1.0)
    return maximum


def calculate_features(
    bars: Sequence[DailyBar], config: ETFRotationConfig = DEFAULT_CONFIG
) -> FeatureSet | None:
    """Calculate V2 features from bars ordered oldest to newest.

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
    volumes = [
        max(0.0, float(item.volume)) if math.isfinite(float(item.volume)) else 0.0
        for item in ordered[-20:]
    ]
    average_volume_20d = statistics.fmean(volumes)
    volume_ratio = statistics.fmean(volumes[-5:]) / average_volume_20d if average_volume_20d > 0 else None
    amounts = [
        max(0.0, float(item.amount))
        for item in ordered[-20:]
        if item.amount is not None and math.isfinite(float(item.amount))
    ]
    average_amount = statistics.fmean(amounts) if amounts else None
    slope_10d, _ = _weighted_log_regression(
        closes[-config.regression_short_window:], config.regression_oldest_weight, config.regression_latest_weight
    )
    slope_25d, r2_25d = _weighted_log_regression(
        closes[-config.regression_long_window:], config.regression_oldest_weight, config.regression_latest_weight
    )
    annualized_10d = _annualize_slope(slope_10d, config.annualized_slope_clip)
    annualized_25d = _annualize_slope(slope_25d, config.annualized_slope_clip)
    efficiency_changes = [
        abs(closes[index] - closes[index - 1])
        for index in range(len(closes) - config.efficiency_window, len(closes))
    ]
    efficiency_denominator = sum(efficiency_changes)
    efficiency = (
        abs(closes[-1] - closes[-1 - config.efficiency_window]) / efficiency_denominator
        if efficiency_denominator > 0 else 0.0
    )
    risk_window = config.risk_adjusted_window
    returns_60d = [
        closes[index] / closes[index - 1] - 1.0 for index in range(len(closes) - risk_window, len(closes))
    ]
    horizon_vol_60d = statistics.stdev(returns_60d) * math.sqrt(risk_window) if len(returns_60d) > 1 else 0.0
    risk_adjusted = returns[risk_window] / horizon_vol_60d if horizon_vol_60d > 1e-12 else 0.0
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
        weighted_slope_10d=slope_10d,
        weighted_slope_25d=slope_25d,
        annualized_slope_10d=annualized_10d,
        annualized_slope_25d=annualized_25d,
        trend_r2_25d=r2_25d,
        trend_quality_25d=annualized_25d * r2_25d,
        efficiency_ratio_20d=efficiency,
        trend_acceleration=annualized_10d - annualized_25d,
        risk_adjusted_momentum_60d=risk_adjusted,
        max_drawdown_20d=_maximum_drawdown(closes[-21:]),
        max_drawdown_60d=_maximum_drawdown(closes[-61:]),
    )


__all__ = ["MINIMUM_HISTORY_BARS", "calculate_features"]

"""Point-in-time trend, breakout, compression, and ATR features."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np

from finance_analysis.trend_following.models import DailyBar


def _return(closes: np.ndarray, window: int) -> float:
    return float(closes[-1] / closes[-window - 1] - 1.0)


def _maximum_drawdown(closes: np.ndarray, window: int) -> float:
    values = closes[-window:]
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1.0))


def weighted_log_regression(closes: Sequence[float], window: int = 15) -> tuple[float, float]:
    """Return recent-weighted log-price slope and weighted R²."""
    values = np.asarray(closes[-window:], dtype=float)
    if len(values) < window or np.any(values <= 0):
        raise ValueError(f"weighted regression requires {window} positive closes")
    x = np.arange(window, dtype=float)
    y = np.log(values)
    weights = np.arange(1, window + 1, dtype=float)
    mean_x = float(np.average(x, weights=weights))
    mean_y = float(np.average(y, weights=weights))
    covariance = float(np.sum(weights * (x - mean_x) * (y - mean_y)))
    variance_x = float(np.sum(weights * (x - mean_x) ** 2))
    slope = covariance / variance_x
    fitted = mean_y + slope * (x - mean_x)
    total = float(np.sum(weights * (y - mean_y) ** 2))
    residual = float(np.sum(weights * (y - fitted) ** 2))
    r_squared = 1.0 if total <= 1e-15 else max(0.0, min(1.0, 1.0 - residual / total))
    return slope, r_squared


def true_ranges(bars: Sequence[DailyBar]) -> np.ndarray:
    ranges: list[float] = []
    for index, bar in enumerate(bars):
        previous_close = bar.close if index == 0 else bars[index - 1].close
        ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return np.asarray(ranges, dtype=float)


def calculate_atr(bars: Sequence[DailyBar], window: int = 20) -> float:
    if len(bars) < window + 1:
        raise ValueError(f"ATR requires at least {window + 1} bars")
    return float(np.mean(true_ranges(bars)[-window:]))


def percentile_ranks(values: Iterable[float]) -> list[float]:
    """Return stable average-tie percentile ranks on a 0..100 scale."""
    items = np.asarray(list(values), dtype=float)
    if len(items) == 0:
        return []
    if len(items) == 1:
        return [100.0]
    order = np.argsort(items, kind="stable")
    ranks = np.empty(len(items), dtype=float)
    start = 0
    while start < len(items):
        end = start
        while end + 1 < len(items) and items[order[end + 1]] == items[order[start]]:
            end += 1
        ranks[order[start : end + 1]] = (start + end) / 2.0
        start = end + 1
    return (ranks / (len(items) - 1) * 100.0).tolist()


def absolute_trend_passes(checks: Iterable[bool]) -> bool:
    values = [bool(value) for value in checks]
    if len(values) != 4:
        raise ValueError("absolute trend requires exactly four checks")
    return sum(values) >= 3


def calculate_features(bars: Sequence[DailyBar], minimum_bars: int = 21) -> dict[str, Any] | None:
    ordered = sorted(bars, key=lambda item: item.trade_date)
    if len(ordered) < minimum_bars:
        return None
    closes = np.asarray([bar.close for bar in ordered], dtype=float)
    highs = np.asarray([bar.high for bar in ordered], dtype=float)
    lows = np.asarray([bar.low for bar in ordered], dtype=float)
    volumes = np.asarray([bar.volume for bar in ordered], dtype=float)
    if np.any(closes <= 0):
        return None
    ma10 = float(np.mean(closes[-10:]))
    ma20 = float(np.mean(closes[-20:]))
    previous_ma10 = float(np.mean(closes[-11:-1]))
    previous_ma20 = float(np.mean(closes[-21:-1]))
    slope, r_squared = weighted_log_regression(closes, 15)
    atr20 = calculate_atr(ordered, 20)
    previous_high_10 = float(np.max(highs[-11:-1]))
    previous_high_20 = float(np.max(highs[-21:-1]))
    previous_low_10 = float(np.min(lows[-11:-1]))
    recent_structure_low = float(np.min(lows[-21:-1]))
    breakout_10 = bool(closes[-1] > previous_high_10)
    breakout_20 = bool(closes[-1] > previous_high_20)
    previous_range_10 = float(np.max(highs[-11:-1]) - np.min(lows[-11:-1]))
    previous_range_20 = float(np.max(highs[-21:-1]) - np.min(lows[-21:-1]))
    prior_tr = true_ranges(ordered[:-1])
    atr_contraction = float(np.mean(prior_tr[-10:])) <= float(np.mean(prior_tr[-20:])) * 0.8
    range_contraction = previous_range_20 > 0 and previous_range_10 / previous_range_20 <= 0.6
    prior_compression = bool(atr_contraction and range_contraction)
    compression_breakout = bool(prior_compression and breakout_10)
    previous_volume = volumes[-21:-1]
    average_volume = float(np.mean(previous_volume))
    volume_ratio = float(volumes[-1] / average_volume) if average_volume > 0 else 0.0
    base_high = previous_high_20 if breakout_20 else previous_high_10
    breakout_distance = max(0.0, float(closes[-1] / base_high - 1.0)) if breakout_10 else 0.0
    return_3d = _return(closes, 3)
    return_5d = _return(closes, 5)
    return_10d = _return(closes, 10)
    return_20d = _return(closes, 20)
    absolute_trend_checks = {
        "close_above_ma10": bool(closes[-1] > ma10),
        "ma10_above_ma20": bool(ma10 > ma20),
        "return_10d_positive": bool(return_10d > 0),
        "weighted_slope_15d_positive": bool(slope > 0),
    }
    absolute_trend_count = sum(absolute_trend_checks.values())
    trend_resume_base = bool(
        closes[-1] > ma10
        and ma10 > ma20
        and slope > 0
        and (return_3d > 0 or return_5d > 0)
    )
    setup = "NONE"
    if compression_breakout:
        setup = "COMPRESSION_BREAKOUT"
    elif breakout_20:
        setup = "BREAKOUT_20D"
    elif breakout_10:
        setup = "BREAKOUT_10D"
    return {
        "open": float(ordered[-1].open),
        "reference_price": float(closes[-1]),
        "ma10": ma10,
        "ma20": ma20,
        "ma10_slope": ma10 / previous_ma10 - 1.0,
        "ma20_slope": ma20 / previous_ma20 - 1.0,
        "absolute_trend_checks": absolute_trend_checks,
        "absolute_trend_count": absolute_trend_count,
        "trend_candidate": absolute_trend_passes(absolute_trend_checks.values()),
        "raw_weighted_slope": float(slope),
        "weighted_r2": float(r_squared),
        "return_3d": return_3d,
        "return_5d": return_5d,
        "return_10d": return_10d,
        "return_20d": return_20d,
        "drawdown_20d": _maximum_drawdown(closes, 20),
        "atr20": atr20,
        "previous_high_10": previous_high_10,
        "previous_high_20": previous_high_20,
        "previous_low_10": previous_low_10,
        "recent_structure_low": recent_structure_low,
        "breakout_10d": breakout_10,
        "breakout_20d": breakout_20,
        "compression_breakout": compression_breakout,
        "prior_compression": prior_compression,
        "trend_resume_base": trend_resume_base,
        "trend_resume": False,
        "breakout_distance": breakout_distance,
        "volume_ratio": volume_ratio,
        "distance_from_ma20": float(closes[-1] / ma20 - 1.0),
        "breakout_10d_strength": max(0.0, float((closes[-1] - previous_high_10) / max(atr20, 1e-12))),
        "breakout_20d_strength": max(0.0, float((closes[-1] - previous_high_20) / max(atr20, 1e-12))),
        "valid_setup": bool(breakout_10 or breakout_20 or compression_breakout),
        "setup": setup,
    }


def finite(value: float, fallback: float = 0.0) -> float:
    return float(value) if math.isfinite(value) else fallback


__all__ = [
    "absolute_trend_passes",
    "calculate_atr",
    "calculate_features",
    "percentile_ranks",
    "true_ranges",
    "weighted_log_regression",
]

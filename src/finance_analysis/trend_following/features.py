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


def weighted_log_regression(closes: Sequence[float], window: int = 25) -> tuple[float, float]:
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


def calculate_features(bars: Sequence[DailyBar], minimum_bars: int = 61) -> dict[str, Any] | None:
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
    ma60 = float(np.mean(closes[-60:]))
    previous_ma20 = float(np.mean(closes[-21:-1]))
    slope, r_squared = weighted_log_regression(closes, 25)
    atr20 = calculate_atr(ordered, 20)
    previous_high_20 = float(np.max(highs[-21:-1]))
    previous_high_55 = float(np.max(highs[-56:-1]))
    previous_low_10 = float(np.min(lows[-11:-1]))
    recent_structure_low = float(np.min(lows[-21:-1]))
    breakout_20 = bool(closes[-1] > previous_high_20)
    breakout_55 = bool(closes[-1] > previous_high_55)
    previous_range_20 = float(np.max(highs[-21:-1]) - np.min(lows[-21:-1]))
    previous_range_60 = float(np.max(highs[-61:-1]) - np.min(lows[-61:-1]))
    prior_tr = true_ranges(ordered[:-1])
    atr_contraction = float(np.mean(prior_tr[-20:])) <= float(np.mean(prior_tr[-40:])) * 0.8
    range_contraction = previous_range_60 > 0 and previous_range_20 / previous_range_60 <= 0.6
    prior_compression = bool(atr_contraction and range_contraction)
    compression_breakout = bool(prior_compression and breakout_20)
    previous_volume = volumes[-21:-1]
    average_volume = float(np.mean(previous_volume))
    volume_ratio = float(volumes[-1] / average_volume) if average_volume > 0 else 0.0
    base_high = previous_high_55 if breakout_55 else previous_high_20
    breakout_distance = max(0.0, float(closes[-1] / base_high - 1.0)) if (breakout_20 or breakout_55) else 0.0
    setup = "NONE"
    if breakout_55:
        setup = "BREAKOUT_55D"
    elif compression_breakout:
        setup = "COMPRESSION_BREAKOUT"
    elif breakout_20:
        setup = "BREAKOUT_20D"
    return {
        "reference_price": float(closes[-1]),
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "ma20_slope": ma20 / previous_ma20 - 1.0,
        "trend_candidate": bool(closes[-1] > ma20 > ma60 and ma20 > previous_ma20),
        "raw_weighted_slope": float(slope),
        "weighted_r2": float(r_squared),
        "return_20d": _return(closes, 20),
        "return_60d": _return(closes, 60),
        "drawdown_20d": _maximum_drawdown(closes, 20),
        "drawdown_60d": _maximum_drawdown(closes, 60),
        "atr20": atr20,
        "previous_high_20": previous_high_20,
        "previous_high_55": previous_high_55,
        "previous_low_10": previous_low_10,
        "recent_structure_low": recent_structure_low,
        "breakout_20d": breakout_20,
        "breakout_55d": breakout_55,
        "compression_breakout": compression_breakout,
        "prior_compression": prior_compression,
        "breakout_distance": breakout_distance,
        "volume_ratio": volume_ratio,
        "distance_from_ma20": float(closes[-1] / ma20 - 1.0),
        "breakout_20d_strength": max(0.0, float((closes[-1] - previous_high_20) / max(atr20, 1e-12))),
        "breakout_55d_strength": max(0.0, float((closes[-1] - previous_high_55) / max(atr20, 1e-12))),
        "valid_setup": bool(breakout_20 or breakout_55 or compression_breakout),
        "setup": setup,
    }


def finite(value: float, fallback: float = 0.0) -> float:
    return float(value) if math.isfinite(value) else fallback


__all__ = ["calculate_atr", "calculate_features", "percentile_ranks", "true_ranges", "weighted_log_regression"]

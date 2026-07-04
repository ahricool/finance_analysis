"""Leakage-safe daily features and T+1-open/T+5-close labels."""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_BAR_COLUMNS = {"date", "open", "high", "low", "close", "volume"}


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.divide(denominator.replace(0, np.nan))


def build_daily_features(bars: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_BAR_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"Missing daily bar columns: {sorted(missing)}")
    frame = bars.copy().sort_values("date", kind="stable").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise ValueError("Duplicate daily dates are not allowed")
    close, high, low, volume = frame["close"].astype(float), frame["high"].astype(float), frame["low"].astype(float), frame["volume"].astype(float)
    for days in (1, 5, 20, 60):
        frame[f"ret_{days}d"] = close.pct_change(days)
    frame["price_ma20_ratio"] = _safe_ratio(close, close.rolling(20, min_periods=20).mean()) - 1
    frame["price_ma60_ratio"] = _safe_ratio(close, close.rolling(60, min_periods=60).mean()) - 1
    frame["volume_ratio_5d"] = _safe_ratio(volume, volume.rolling(5, min_periods=5).mean())
    previous_close = close.shift(1)
    true_range = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    frame["atr_14"] = true_range.rolling(14, min_periods=14).mean()
    frame["realized_vol_20d"] = close.pct_change().rolling(20, min_periods=20).std(ddof=1) * np.sqrt(252)
    frame["distance_from_20d_high"] = _safe_ratio(close, high.rolling(20, min_periods=20).max()) - 1
    frame["gap_return"] = _safe_ratio(frame["open"].astype(float), previous_close) - 1
    delta = close.diff(); gains = delta.clip(lower=0); losses = -delta.clip(upper=0)
    rs = _safe_ratio(gains.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean(), losses.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean())
    frame["rsi_14"] = 100 - 100 / (1 + rs)
    return frame


def add_relative_strength(stock: pd.DataFrame, market: pd.DataFrame, sector: pd.DataFrame) -> pd.DataFrame:
    result = stock.copy()
    for prefix, benchmark in (("market", market), ("sector", sector)):
        aligned = benchmark[["date", "close"]].sort_values("date").copy()
        for days in (5, 20):
            aligned[f"benchmark_ret_{days}d"] = aligned["close"].pct_change(days)
        columns = ["date", "benchmark_ret_5d", "benchmark_ret_20d"]
        result = result.merge(aligned[columns], on="date", how="left", validate="one_to_one")
        for days in (5, 20):
            result[f"relative_{days}d_to_{prefix}"] = result[f"ret_{days}d"] - result.pop(f"benchmark_ret_{days}d")
    return result


def build_forward_excess_label(stock: pd.DataFrame, benchmark: pd.DataFrame, horizon: int = 5) -> pd.Series:
    """Return percentage points; row T uses T+1 open and T+5 close only."""
    if horizon < 1: raise ValueError("horizon must be positive")
    left = stock[["date", "open", "close"]].sort_values("date").reset_index(drop=True)
    right = benchmark[["date", "open", "close"]].sort_values("date").reset_index(drop=True)
    merged = left.merge(right, on="date", suffixes=("_stock", "_benchmark"), validate="one_to_one")
    stock_return = merged["close_stock"].shift(-horizon) / merged["open_stock"].shift(-1) - 1
    benchmark_return = merged["close_benchmark"].shift(-horizon) / merged["open_benchmark"].shift(-1) - 1
    return (stock_return - benchmark_return) * 100

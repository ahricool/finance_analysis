"""Shared RSI series; legacy rolling RSI and seeded Wilder smoothing."""

import numpy as np
import pandas as pd


def rsi_series(close: pd.Series, period: int = 14, *, wilder: bool = False) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    if not wilder:
        # Preserve the technical analyzer's existing rolling formula and warmup.
        rs = gain.rolling(period).mean() / loss.rolling(period).mean()
        return (100 - 100 / (1 + rs)).fillna(50)
    values = np.full(len(close), np.nan)
    if len(close) <= period:
        return pd.Series(values, index=close.index)
    avg_gain, avg_loss = gain.iloc[1 : period + 1].mean(), loss.iloc[1 : period + 1].mean()
    for i in range(period, len(close)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
            avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period
        values[i] = 50 if avg_gain == avg_loss == 0 else 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return pd.Series(values, index=close.index)

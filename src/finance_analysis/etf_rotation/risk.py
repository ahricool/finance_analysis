"""Pure execution-risk metadata calculations shared by every ETF market."""

from __future__ import annotations

import math

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig

TRADING_DAYS_PER_YEAR = 252


def _require_finite(value: float, field_name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


def calculate_stop_loss_pct(
    realized_vol_20d: float,
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> float:
    """Return a volatility-scaled initial stop distance, clamped by config."""
    annualized_vol = _require_finite(realized_vol_20d, "realized_vol_20d")
    multiplier = _require_finite(config.stop_vol_multiplier, "stop_vol_multiplier")
    minimum = _require_finite(config.minimum_stop_pct, "minimum_stop_pct")
    maximum = _require_finite(config.maximum_stop_pct, "maximum_stop_pct")
    if annualized_vol < 0:
        raise ValueError("realized_vol_20d must be greater than or equal to 0")
    if multiplier < 0:
        raise ValueError("stop_vol_multiplier must be greater than or equal to 0")
    if not 0 <= minimum <= maximum < 1:
        raise ValueError("stop-loss bounds must satisfy 0 <= minimum <= maximum < 1")
    daily_vol = annualized_vol / math.sqrt(TRADING_DAYS_PER_YEAR)
    return min(max(multiplier * daily_vol, minimum), maximum)


def calculate_suggested_stop_price(reference_price: float, stop_loss_pct: float) -> float:
    """Calculate an initial stop reference from the same snapshot's close."""
    price = _require_finite(reference_price, "reference_price")
    stop_pct = _require_finite(stop_loss_pct, "stop_loss_pct")
    if price <= 0:
        raise ValueError("reference_price must be greater than 0")
    if not 0 <= stop_pct < 1:
        raise ValueError("stop_loss_pct must satisfy 0 <= stop_loss_pct < 1")
    return price * (1.0 - stop_pct)


__all__ = ["TRADING_DAYS_PER_YEAR", "calculate_stop_loss_pct", "calculate_suggested_stop_price"]

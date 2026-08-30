"""Public market-data eligibility gates for ETF Rotation V2."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig


def is_absolute_trend_eligible(
    row: Mapping[str, Any], config: ETFRotationConfig = DEFAULT_CONFIG
) -> bool:
    if config.absolute_trend_require_positive_slope and float(row["weighted_slope_25d"]) <= 0:
        return False
    secondary = (float(row["ma60_ratio"]) > 0, float(row["ret_60d"]) > 0)
    return sum(secondary) >= config.absolute_trend_min_secondary_conditions


def is_liquidity_eligible(
    row: Mapping[str, Any], market: str, config: ETFRotationConfig = DEFAULT_CONFIG
) -> bool:
    amount = row.get("avg_amount_20d")
    return amount is not None and float(amount) >= config.minimum_liquidity[market]


__all__ = ["is_absolute_trend_eligible", "is_liquidity_eligible"]

"""Public market-data eligibility gates for fast ETF rotation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig


def is_absolute_trend_eligible(
    row: Mapping[str, Any], config: ETFRotationConfig = DEFAULT_CONFIG
) -> bool:
    conditions = (
        float(row["ret_5d"]) > 0,
        float(row["weighted_slope_10d"]) > 0,
        float(row["ma10_ratio"]) > 0,
    )
    return sum(conditions) >= config.absolute_trend_min_conditions


def is_liquidity_eligible(
    row: Mapping[str, Any], market: str, config: ETFRotationConfig = DEFAULT_CONFIG
) -> bool:
    amount = row.get("avg_amount_20d")
    return amount is not None and float(amount) >= config.minimum_liquidity[market]


__all__ = ["is_absolute_trend_eligible", "is_liquidity_eligible"]

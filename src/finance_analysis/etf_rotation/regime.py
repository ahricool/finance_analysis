"""Simple, explainable market-regime classification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig


def calculate_market_regime(
    rows: Sequence[Mapping[str, Any]],
    benchmark: Mapping[str, Any],
    *,
    market: str,
    trade_date,
    benchmark_code: str,
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    count = len(rows)
    positive_5d_breadth = sum(float(row["ret_5d"]) > 0 for row in rows) / count if count else 0.0
    above_ma10_breadth = sum(float(row["ma10_ratio"]) > 0 for row in rows) / count if count else 0.0
    benchmark_ret_5d = float(benchmark["ret_5d"])
    benchmark_slope_10d = float(benchmark["weighted_slope_10d"])
    if (
        positive_5d_breadth >= config.regime_risk_on_breadth
        and above_ma10_breadth >= config.regime_risk_on_breadth
        and benchmark_ret_5d > 0
        and benchmark_slope_10d > 0
    ):
        regime = "RISK_ON"
    elif (
        positive_5d_breadth <= config.regime_risk_off_breadth
        and above_ma10_breadth <= config.regime_risk_off_breadth
        and benchmark_ret_5d < 0
        and benchmark_slope_10d < 0
    ):
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"
    return {
        "trade_date": trade_date,
        "market": market,
        "regime": regime,
        "positive_5d_breadth": positive_5d_breadth,
        "above_ma10_breadth": above_ma10_breadth,
        "benchmark_code": benchmark_code,
        "benchmark_close": benchmark["reference_price"],
        "benchmark_ret_5d": benchmark_ret_5d,
        "benchmark_ma10_ratio": benchmark["ma10_ratio"],
        "benchmark_weighted_slope_10d": benchmark_slope_10d,
        "benchmark_trend": (
            "POSITIVE"
            if benchmark_ret_5d > 0 and benchmark_slope_10d > 0
            else "NEGATIVE" if benchmark_ret_5d < 0 and benchmark_slope_10d < 0 else "MIXED"
        ),
    }


__all__ = ["calculate_market_regime"]

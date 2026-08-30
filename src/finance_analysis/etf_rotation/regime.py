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
    breadth_ma20 = sum(float(row["ma20_ratio"]) > 0 for row in rows) / count if count else 0.0
    breadth_ma60 = sum(float(row["ma60_ratio"]) > 0 for row in rows) / count if count else 0.0
    breadth_cross = sum(float(row["ma20_ratio"]) < float(row["ma60_ratio"]) for row in rows) / count if count else 0.0
    above_ma20 = float(benchmark["ma20_ratio"]) > 0
    above_ma60 = float(benchmark["ma60_ratio"]) > 0
    ma20_above_ma60 = float(benchmark["ma20_ratio"]) < float(benchmark["ma60_ratio"])
    trend_positive = float(benchmark["weighted_slope_25d"]) > 0
    if breadth_ma60 > config.regime_risk_on_breadth_ma60 and above_ma60 and trend_positive:
        regime = "RISK_ON"
    elif breadth_ma60 < config.regime_risk_off_breadth_ma60 and not above_ma60:
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"
    return {
        "trade_date": trade_date,
        "market": market,
        "regime": regime,
        "breadth_above_ma20": breadth_ma20,
        "breadth_above_ma60": breadth_ma60,
        "breadth_ma20_above_ma60": breadth_cross,
        "benchmark_code": benchmark_code,
        "benchmark_close": benchmark["reference_price"],
        "benchmark_ma20_ratio": benchmark["ma20_ratio"],
        "benchmark_ma60_ratio": benchmark["ma60_ratio"],
        "benchmark_trend": (
            "POSITIVE"
            if trend_positive and above_ma60
            else "NEGATIVE" if not trend_positive and not above_ma60 else "MIXED"
        ),
        "benchmark_above_ma20": above_ma20,
        "benchmark_above_ma60": above_ma60,
        "benchmark_ma20_above_ma60": ma20_above_ma60,
    }


__all__ = ["calculate_market_regime"]

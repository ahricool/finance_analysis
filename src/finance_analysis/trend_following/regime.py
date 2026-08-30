"""Market regime computed only from raw benchmark and universe bars."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date

import numpy as np

from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .models import DailyBar
from .scoring import clamp


def realized_volatility_20d(closes: np.ndarray) -> float:
    """Annualize sample volatility from exactly 20 daily returns (21 closes)."""
    recent = np.asarray(closes[-21:], dtype=float)
    if len(recent) < 21:
        raise ValueError("realized volatility requires 21 closes")
    daily_returns = recent[1:] / recent[:-1] - 1.0
    if len(daily_returns) != 20:
        raise ValueError("realized volatility must use exactly 20 daily returns")
    return float(np.std(daily_returns, ddof=1) * math.sqrt(252.0))


def calculate_market_regime(
    benchmark_bars: Sequence[DailyBar],
    universe_bars: Mapping[str, Sequence[DailyBar]],
    *,
    market: str,
    trade_date: date,
    benchmark_code: str,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> dict:
    ordered = sorted(benchmark_bars, key=lambda item: item.trade_date)
    if len(ordered) < config.minimum_history_bars or ordered[-1].trade_date != trade_date:
        raise ValueError(f"benchmark {benchmark_code} has insufficient point-in-time history")
    closes = np.asarray([bar.close for bar in ordered], dtype=float)
    benchmark_close = float(closes[-1])
    ma20 = float(np.mean(closes[-20:]))
    ma60 = float(np.mean(closes[-60:]))
    return_20d = float(closes[-1] / closes[-21] - 1.0)
    return_60d = float(closes[-1] / closes[-61] - 1.0)
    realized_vol = realized_volatility_20d(closes)
    peaks = np.maximum.accumulate(closes[-60:])
    max_drawdown_60d = float(np.min(closes[-60:] / peaks - 1.0))

    ready = 0
    up = above20 = above60 = high20 = low20 = 0
    for bars in universe_bars.values():
        values = sorted((bar for bar in bars if bar.trade_date <= trade_date), key=lambda item: item.trade_date)
        if len(values) < config.minimum_history_bars or values[-1].trade_date != trade_date:
            continue
        stock_closes = np.asarray([bar.close for bar in values], dtype=float)
        ready += 1
        up += int(stock_closes[-1] > stock_closes[-2])
        above20 += int(stock_closes[-1] > np.mean(stock_closes[-20:]))
        above60 += int(stock_closes[-1] > np.mean(stock_closes[-60:]))
        high20 += int(stock_closes[-1] > np.max(stock_closes[-21:-1]))
        low20 += int(stock_closes[-1] < np.min(stock_closes[-21:-1]))
    divisor = max(ready, 1)
    breadth = {
        "up_ratio": up / divisor,
        "above_ma20_ratio": above20 / divisor,
        "above_ma60_ratio": above60 / divisor,
        "high_20d_count": high20,
        "low_20d_count": low20,
    }
    trend_score = np.mean([
        100.0 if benchmark_close > ma20 else 0.0,
        100.0 if benchmark_close > ma60 else 0.0,
        clamp(50.0 + return_20d * 300.0),
        clamp(50.0 + return_60d * 200.0),
    ])
    breadth_score = np.mean([
        breadth["up_ratio"] * 100.0,
        breadth["above_ma20_ratio"] * 100.0,
        breadth["above_ma60_ratio"] * 100.0,
        clamp(50.0 + (high20 - low20) / divisor * 200.0),
    ])
    risk_score = np.mean([
        clamp(100.0 - realized_vol * 180.0),
        clamp(100.0 + max_drawdown_60d * 300.0),
    ])
    components = {"trend": float(trend_score), "breadth": float(breadth_score), "risk": float(risk_score)}
    market_score = sum(components[key] * weight for key, weight in config.regime_weights.items())
    regime = "RISK_ON" if market_score >= config.risk_on_threshold else (
        "RISK_OFF" if market_score < config.risk_off_threshold else "NEUTRAL"
    )
    return {
        "market": market,
        "trade_date": trade_date,
        "benchmark_code": benchmark_code,
        "market_regime": regime,
        "market_score": round(float(market_score), 4),
        "suggested_max_exposure": config.regime_max_exposure[regime],
        "features": {
            "benchmark_close": benchmark_close,
            "benchmark_ma20": ma20,
            "benchmark_ma60": ma60,
            "benchmark_vs_ma20": benchmark_close / ma20 - 1.0,
            "benchmark_vs_ma60": benchmark_close / ma60 - 1.0,
            "benchmark_return_20d": return_20d,
            "benchmark_return_60d": return_60d,
            "realized_volatility_20d": realized_vol,
            "max_drawdown_60d": max_drawdown_60d,
            **breadth,
            "breadth_ready_count": ready,
        },
        "score_breakdown": components,
    }


__all__ = ["calculate_market_regime", "realized_volatility_20d"]

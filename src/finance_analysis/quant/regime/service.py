"""Transparent, market-neutral regime rules with explicit benchmark labels."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from finance_analysis.quant.config import RegimeConfig


@dataclass(frozen=True)
class MarketRegimeResult:
    regime: str
    market_score: float
    max_equity_exposure: float
    sector_permissions: dict[str, bool]
    features: dict
    reasons: list[str]


class MarketRegimeService:
    def __init__(self, config: RegimeConfig | None = None):
        self.config = config or RegimeConfig()

    def calculate(
        self,
        primary: pd.DataFrame,
        broad: pd.DataFrame,
        universe: dict[str, pd.DataFrame],
        *,
        benchmark_labels: tuple[str, str] = ("primary", "broad"),
    ) -> MarketRegimeResult:
        for name, frame in zip(benchmark_labels, (primary, broad)):
            if len(frame) < 61:
                raise ValueError(f"{name} requires at least 61 daily bars")
        primary, broad = (
            frame.sort_values("date").reset_index(drop=True)
            for frame in (primary, broad)
        )

        def ret(frame: pd.DataFrame, periods: int) -> float:
            return float(frame["close"].iloc[-1] / frame["close"].iloc[-periods - 1] - 1)

        close = primary["close"].astype(float)
        daily_return = close.pct_change()
        drawdown = close / close.cummax() - 1
        breadth20, breadth60, up = [], [], []
        highs = lows = 0
        for frame in universe.values():
            ordered = frame.sort_values("date")
            if len(ordered) < 61:
                continue
            member_close = ordered["close"].astype(float)
            up.append(member_close.iloc[-1] > member_close.iloc[-2])
            breadth20.append(member_close.iloc[-1] > member_close.iloc[-20:].mean())
            breadth60.append(member_close.iloc[-1] > member_close.iloc[-60:].mean())
            highs += member_close.iloc[-1] >= member_close.iloc[-20:].max()
            lows += member_close.iloc[-1] <= member_close.iloc[-20:].min()
        features = {
            "primary_benchmark": benchmark_labels[0],
            "broad_benchmark": benchmark_labels[1],
            "primary_ma20_ratio": float(close.iloc[-1] / close.iloc[-20:].mean() - 1),
            "primary_ma60_ratio": float(close.iloc[-1] / close.iloc[-60:].mean() - 1),
            "primary_ret_5d": ret(primary, 5),
            "primary_ret_20d": ret(primary, 20),
            "primary_ret_60d": ret(primary, 60),
            "broad_ret_5d": ret(broad, 5),
            "broad_ret_20d": ret(broad, 20),
            "primary_relative_broad_20d": ret(primary, 20) - ret(broad, 20),
            "primary_realized_vol_20d": float(daily_return.tail(20).std(ddof=1) * math.sqrt(252)),
            "primary_max_drawdown_60d": float(drawdown.tail(60).min()),
            "universe_up_ratio": float(np.mean(up)) if up else None,
            "universe_above_ma20_ratio": float(np.mean(breadth20)) if breadth20 else None,
            "universe_above_ma60_ratio": float(np.mean(breadth60)) if breadth60 else None,
            # Pandas comparisons return numpy.bool_; accumulating them promotes
            # the counters to numpy.int64, which PostgreSQL JSONB cannot encode.
            "universe_20d_high_count": int(highs),
            "universe_20d_low_count": int(lows),
            "vix": None,
            "advance_decline_volume": None,
        }
        components = [
            np.clip((features["primary_ma20_ratio"] + 0.05) / 0.10, 0, 1),
            np.clip((features["primary_ma60_ratio"] + 0.10) / 0.20, 0, 1),
            np.clip((features["primary_ret_20d"] + 0.10) / 0.20, 0, 1),
            np.clip((features["broad_ret_20d"] + 0.10) / 0.20, 0, 1),
            np.clip((features["primary_relative_broad_20d"] + 0.08) / 0.16, 0, 1),
            np.clip((0.45 - features["primary_realized_vol_20d"]) / 0.35, 0, 1),
        ]
        components.extend(
            value
            for value in (
                features["universe_up_ratio"],
                features["universe_above_ma20_ratio"],
                features["universe_above_ma60_ratio"],
            )
            if value is not None
        )
        score = float(np.mean(components))
        if score >= self.config.risk_on_threshold:
            regime, exposure = "risk_on", self.config.risk_on_exposure
        elif score <= self.config.risk_off_threshold:
            regime, exposure = "risk_off", self.config.risk_off_exposure
        else:
            regime, exposure = "neutral", self.config.neutral_exposure
        reasons = [
            f"{benchmark_labels[0]}相对MA20 {features['primary_ma20_ratio']:.1%}",
            f"{benchmark_labels[0]} 20日收益 {features['primary_ret_20d']:.1%}",
            f"{benchmark_labels[0]} 20日波动率 {features['primary_realized_vol_20d']:.1%}",
        ]
        return MarketRegimeResult(regime, score, exposure, {"ranking": regime != "risk_off"}, features, reasons)

    @staticmethod
    def intraday_features(primary: pd.DataFrame, risk: pd.DataFrame) -> dict:
        def values(frame):
            ordered = frame.sort_values("bar_time")
            cumulative_volume = ordered["volume"].cumsum()
            vwap = (ordered["close"] * ordered["volume"]).cumsum() / cumulative_volume.replace(0, np.nan)
            return ordered, vwap

        primary, primary_vwap = values(primary)
        risk, _ = values(risk)
        return {
            "primary_price_vs_vwap": float(primary["close"].iloc[-1] / primary_vwap.iloc[-1] - 1),
            "primary_opening_gap": None,
            "primary_first_30m_return": float(
                primary["close"].iloc[min(29, len(primary) - 1)] / primary["open"].iloc[0] - 1
            ),
            "risk_relative_primary": float(
                (risk["close"].iloc[-1] / risk["open"].iloc[0])
                - (primary["close"].iloc[-1] / primary["open"].iloc[0])
            ),
        }

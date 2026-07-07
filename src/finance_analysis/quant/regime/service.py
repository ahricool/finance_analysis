"""Transparent market regime rules with optional features left as null."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

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
    def __init__(self, config: RegimeConfig | None = None): self.config = config or RegimeConfig()

    def calculate(self, qqq: pd.DataFrame, spy: pd.DataFrame, soxx: pd.DataFrame, universe: dict[str, pd.DataFrame]) -> MarketRegimeResult:
        for name, frame in (("QQQ", qqq), ("SPY", spy), ("SOXX", soxx)):
            if len(frame) < 61: raise ValueError(f"{name} requires at least 61 daily bars")
        q, s, x = (frame.sort_values("date").reset_index(drop=True) for frame in (qqq, spy, soxx))
        ret = lambda frame, n: float(frame["close"].iloc[-1] / frame["close"].iloc[-n - 1] - 1)
        qclose = q["close"].astype(float); qret = qclose.pct_change()
        drawdown = qclose / qclose.cummax() - 1
        breadth20, breadth60, up, highs, lows = [], [], [], 0, 0
        for frame in universe.values():
            ordered = frame.sort_values("date")
            if len(ordered) < 61: continue
            close = ordered["close"].astype(float)
            up.append(close.iloc[-1] > close.iloc[-2]); breadth20.append(close.iloc[-1] > close.iloc[-20:].mean()); breadth60.append(close.iloc[-1] > close.iloc[-60:].mean())
            highs += close.iloc[-1] >= close.iloc[-20:].max(); lows += close.iloc[-1] <= close.iloc[-20:].min()
        features = {
            "qqq_ma20_ratio": float(qclose.iloc[-1] / qclose.iloc[-20:].mean() - 1), "qqq_ma60_ratio": float(qclose.iloc[-1] / qclose.iloc[-60:].mean() - 1),
            "qqq_ret_5d": ret(q, 5), "qqq_ret_20d": ret(q, 20), "qqq_ret_60d": ret(q, 60),
            "spy_ret_5d": ret(s, 5), "spy_ret_20d": ret(s, 20), "soxx_ret_5d": ret(x, 5), "soxx_ret_20d": ret(x, 20),
            "soxx_relative_qqq_20d": ret(x, 20) - ret(q, 20), "qqq_realized_vol_20d": float(qret.tail(20).std(ddof=1) * math.sqrt(252)),
            "qqq_max_drawdown_60d": float(drawdown.tail(60).min()), "universe_up_ratio": float(np.mean(up)) if up else None,
            "universe_above_ma20_ratio": float(np.mean(breadth20)) if breadth20 else None, "universe_above_ma60_ratio": float(np.mean(breadth60)) if breadth60 else None,
            "universe_20d_high_count": highs, "universe_20d_low_count": lows, "vix": None, "advance_decline_volume": None,
        }
        components = [
            np.clip((features["qqq_ma20_ratio"] + .05) / .10, 0, 1), np.clip((features["qqq_ma60_ratio"] + .10) / .20, 0, 1),
            np.clip((features["qqq_ret_20d"] + .10) / .20, 0, 1), np.clip((features["spy_ret_20d"] + .10) / .20, 0, 1),
            np.clip((features["soxx_relative_qqq_20d"] + .08) / .16, 0, 1), np.clip((.45 - features["qqq_realized_vol_20d"]) / .35, 0, 1),
        ]
        components.extend(value for value in (features["universe_up_ratio"], features["universe_above_ma20_ratio"], features["universe_above_ma60_ratio"]) if value is not None)
        score = float(np.mean(components))
        if score >= self.config.risk_on_threshold: regime, exposure = "risk_on", self.config.risk_on_exposure
        elif score <= self.config.risk_off_threshold: regime, exposure = "risk_off", self.config.risk_off_exposure
        else: regime, exposure = "neutral", self.config.neutral_exposure
        reasons = [f"QQQ相对MA20 {features['qqq_ma20_ratio']:.1%}", f"QQQ 20日收益 {features['qqq_ret_20d']:.1%}", f"QQQ 20日波动率 {features['qqq_realized_vol_20d']:.1%}"]
        return MarketRegimeResult(regime, score, exposure, {"semiconductor": regime != "risk_off"}, features, reasons)

    @staticmethod
    def intraday_features(qqq: pd.DataFrame, soxx: pd.DataFrame) -> dict:
        def values(frame):
            ordered = frame.sort_values("bar_time"); cumulative_volume = ordered["volume"].cumsum(); vwap = (ordered["close"] * ordered["volume"]).cumsum() / cumulative_volume.replace(0, np.nan)
            return ordered, vwap
        q, qv = values(qqq); x, _ = values(soxx)
        return {"qqq_price_vs_vwap": float(q["close"].iloc[-1] / qv.iloc[-1] - 1), "qqq_opening_gap": None,
                "qqq_first_30m_return": float(q["close"].iloc[min(29, len(q)-1)] / q["open"].iloc[0] - 1),
                "soxx_relative_qqq": float((x["close"].iloc[-1] / x["open"].iloc[0]) - (q["close"].iloc[-1] / q["open"].iloc[0]))}

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
        self.config.validate()

    def calculate(
        self,
        primary: pd.DataFrame,
        broad: pd.DataFrame,
        universe: dict[str, pd.DataFrame],
        *,
        benchmark_labels: tuple[str, str] = ("primary", "broad"),
        style: pd.DataFrame | None = None,
        style_label: str | None = None,
    ) -> MarketRegimeResult:
        for name, frame in zip(benchmark_labels, (primary, broad)):
            if len(frame) < 61:
                raise ValueError(f"{name} requires at least 61 daily bars")
        if style is not None and len(style) < 61:
            raise ValueError(f"{style_label or 'style'} requires at least 61 daily bars")
        primary, broad = (
            frame.sort_values("date").reset_index(drop=True)
            for frame in (primary, broad)
        )
        style = (
            style.sort_values("date").reset_index(drop=True)
            if style is not None
            else primary
        )
        style_label = style_label or benchmark_labels[0]

        def ret(frame: pd.DataFrame, periods: int) -> float:
            return float(frame["close"].iloc[-1] / frame["close"].iloc[-periods - 1] - 1)

        close = primary["close"].astype(float)
        daily_return = close.pct_change()
        recent_close = close.tail(60)
        drawdown = recent_close / recent_close.cummax() - 1
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
            "style_benchmark": style_label,
            "primary_ma20_ratio": float(close.iloc[-1] / close.iloc[-20:].mean() - 1),
            "primary_ma60_ratio": float(close.iloc[-1] / close.iloc[-60:].mean() - 1),
            "primary_ret_5d": ret(primary, 5),
            "primary_ret_20d": ret(primary, 20),
            "primary_ret_60d": ret(primary, 60),
            "broad_ret_5d": ret(broad, 5),
            "broad_ret_20d": ret(broad, 20),
            "primary_relative_broad_20d": ret(primary, 20) - ret(broad, 20),
            "style_ret_20d": ret(style, 20),
            "style_relative_broad_20d": ret(style, 20) - ret(broad, 20),
            "primary_realized_vol_20d": float(daily_return.tail(20).std(ddof=1) * math.sqrt(252)),
            "primary_max_drawdown_60d": float(drawdown.min()),
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
        ranges = self.config.normalization_ranges
        component_specs = (
            (
                "trend",
                "趋势",
                "trend_ma20",
                f"{benchmark_labels[0]} vs MA20",
                features["primary_ma20_ratio"],
                self._normalize(features["primary_ma20_ratio"], *ranges["trend_ma20"]),
            ),
            (
                "trend",
                "趋势",
                "trend_ma60",
                f"{benchmark_labels[0]} vs MA60",
                features["primary_ma60_ratio"],
                self._normalize(features["primary_ma60_ratio"], *ranges["trend_ma60"]),
            ),
            (
                "trend",
                "趋势",
                "momentum_20d",
                f"{benchmark_labels[0]} 20日动量",
                features["primary_ret_20d"],
                self._normalize(features["primary_ret_20d"], *ranges["momentum_20d"]),
            ),
            (
                "breadth",
                "市场宽度",
                "breadth_up",
                "成分股当日上涨比例",
                features["universe_up_ratio"],
                features["universe_up_ratio"],
            ),
            (
                "breadth",
                "市场宽度",
                "breadth_ma20",
                "成分股高于MA20比例",
                features["universe_above_ma20_ratio"],
                features["universe_above_ma20_ratio"],
            ),
            (
                "breadth",
                "市场宽度",
                "breadth_ma60",
                "成分股高于MA60比例",
                features["universe_above_ma60_ratio"],
                features["universe_above_ma60_ratio"],
            ),
            (
                "risk",
                "风险",
                "realized_volatility_20d",
                f"{benchmark_labels[0]} 20日实现波动率",
                features["primary_realized_vol_20d"],
                self._normalize(
                    features["primary_realized_vol_20d"],
                    *ranges["realized_volatility_20d"],
                    inverse=True,
                ),
            ),
            (
                "risk",
                "风险",
                "max_drawdown_60d",
                f"{benchmark_labels[0]} 60日最大回撤",
                features["primary_max_drawdown_60d"],
                self._normalize(
                    features["primary_max_drawdown_60d"],
                    *ranges["max_drawdown_60d"],
                ),
            ),
            (
                "style",
                "风格 / 风险偏好",
                "style_relative_20d",
                f"{style_label} 相对 {benchmark_labels[1]} 20日表现",
                features["style_relative_broad_20d"],
                self._normalize(
                    features["style_relative_broad_20d"],
                    *ranges["style_relative_20d"],
                ),
            ),
        )
        components = []
        for group_key, group_label, key, label, raw_value, component_score in component_specs:
            if raw_value is None or component_score is None:
                continue
            weight = self.config.component_weights[key]
            components.append(
                {
                    "key": key,
                    "label": label,
                    "group": group_key,
                    "group_label": group_label,
                    "raw_value": float(raw_value),
                    "raw_format": "percent",
                    "score": float(component_score),
                    "weight": weight,
                    "contribution": float(component_score) * weight,
                }
            )
        available_weight_total = sum(item["weight"] for item in components)
        if available_weight_total <= 0:
            raise ValueError("Market regime score has no available weighted components")
        # Re-normalize the available weights so the displayed contributions
        # always add up exactly to the final score, including legacy/sparse data.
        for item in components:
            item["weight"] = item["weight"] / available_weight_total
            item["contribution"] = item["score"] * item["weight"]
        weight_total = sum(item["weight"] for item in components)
        score = float(sum(item["contribution"] for item in components))
        score = float(np.clip(score, 0, 1))
        groups = []
        for group_key, group_label in (
            ("trend", "趋势"),
            ("breadth", "市场宽度"),
            ("risk", "风险"),
            ("style", "风格 / 风险偏好"),
        ):
            group_components = [item for item in components if item["group"] == group_key]
            if not group_components:
                continue
            group_weight = sum(item["weight"] for item in group_components)
            group_contribution = sum(item["contribution"] for item in group_components)
            groups.append(
                {
                    "key": group_key,
                    "label": group_label,
                    "weight": group_weight,
                    "score": group_contribution / group_weight,
                    "contribution": group_contribution,
                    "components": group_components,
                }
            )
        features["score_breakdown"] = {
            "version": "regime-rules-v2",
            "score": score,
            "weight_total": weight_total,
            "groups": groups,
        }
        if score >= self.config.risk_on_threshold:
            regime = "risk_on"
        elif score <= self.config.risk_off_threshold:
            regime = "risk_off"
        else:
            regime = "neutral"
        exposure = self.max_equity_exposure(score)
        reasons = [
            f"{benchmark_labels[0]}相对MA20 {features['primary_ma20_ratio']:.1%}",
            f"{benchmark_labels[0]} 20日收益 {features['primary_ret_20d']:.1%}",
            f"{benchmark_labels[0]} 20日波动率 {features['primary_realized_vol_20d']:.1%}",
            f"{style_label}相对{benchmark_labels[1]} 20日 {features['style_relative_broad_20d']:.1%}",
        ]
        return MarketRegimeResult(regime, score, exposure, {"ranking": regime != "risk_off"}, features, reasons)

    @staticmethod
    def _normalize(value: float, lower: float, upper: float, *, inverse: bool = False) -> float:
        score = float(np.clip((float(value) - lower) / (upper - lower), 0, 1))
        return 1.0 - score if inverse else score

    def max_equity_exposure(self, market_score: float) -> float:
        score = float(np.clip(market_score, 0, 1))
        curve = self.config.exposure_curve
        for (left_score, left_exposure), (right_score, right_exposure) in zip(curve, curve[1:]):
            if score <= right_score:
                if right_score == left_score:
                    return float(right_exposure)
                position = (score - left_score) / (right_score - left_score)
                return float(left_exposure + position * (right_exposure - left_exposure))
        return float(curve[-1][1])

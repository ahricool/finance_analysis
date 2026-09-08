"""Fuse Qlib model scores with market gating and a runtime risk penalty."""

from __future__ import annotations

from dataclasses import dataclass

from finance_analysis.quant.config import FusionConfig


@dataclass(frozen=True)
class FusedSignal:
    final_score: float
    signal: str
    score_components: dict
    reasons: list[str]


class SignalFusion:
    def __init__(self, config: FusionConfig | None = None):
        self.config = config or FusionConfig(); self.config.validate()

    def fuse(
        self,
        cross_section_score: float,
        time_series_score: float,
        market_regime: str,
        market_score: float | None = None,
        risk_penalty: float = 0,
    ) -> FusedSignal:
        pre_regime_score = (
            cross_section_score * self.config.cross_section_weight
            + time_series_score * self.config.time_series_weight
            - risk_penalty
        )
        regime_multiplier = self.config.regime_multipliers[market_regime]
        final_score = pre_regime_score * regime_multiplier
        components = {
            "cross_section_score": cross_section_score,
            "time_series_score": time_series_score,
            "cross_section_weight": self.config.cross_section_weight,
            "time_series_weight": self.config.time_series_weight,
            "risk_penalty": risk_penalty,
            "market_score": market_score,
            "market_regime": market_regime,
            "pre_regime_score": pre_regime_score,
            "regime_multiplier": regime_multiplier,
        }
        reasons = [
            f"横截面得分 {cross_section_score:.2f}",
            f"时间序列得分 {time_series_score:.2f}",
            f"市场状态 {market_regime}",
        ]
        if risk_penalty:
            reasons.append(f"风险扣分 {risk_penalty:.2f}")
        signal = (
            "buy"
            if final_score >= 0.65
            else "watch"
            if final_score >= 0.50
            else "avoid"
            if final_score < 0.35
            else "hold"
        )
        return FusedSignal(final_score, signal, components, reasons)

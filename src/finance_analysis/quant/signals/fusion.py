"""Config-driven score fusion, market gating, risk penalty and veto."""

from __future__ import annotations

from dataclasses import dataclass

from finance_analysis.quant.config import FusionConfig


@dataclass(frozen=True)
class FusedSignal:
    raw_final_score: float
    gated_final_score: float
    final_score: float
    target_position: float
    signal: str
    vetoed: bool
    veto_reason: str | None
    score_components: dict
    reasons: list[str]


class SignalFusion:
    def __init__(self, config: FusionConfig | None = None):
        self.config = config or FusionConfig(); self.config.validate()

    def fuse(self, cross_section_score: float, time_series_score: float, event_score: float, market_regime: str,
             market_score: float | None = None, sector_score: float | None = None, risk_penalty: float = 0,
             negative_event_veto: bool = False, veto_reason: str | None = None) -> FusedSignal:
        components = {"cross_section_score": cross_section_score, "time_series_score": time_series_score, "event_score": event_score,
                      "cross_section_weight": self.config.cross_section_weight, "time_series_weight": self.config.time_series_weight,
                      "event_weight": self.config.event_weight, "risk_penalty": risk_penalty, "market_score": market_score, "sector_score": sector_score}
        raw = cross_section_score*self.config.cross_section_weight + time_series_score*self.config.time_series_weight + event_score*self.config.event_weight - risk_penalty
        gated = raw*self.config.regime_multipliers[market_regime]
        reasons = [f"横截面得分 {cross_section_score:.2f}", f"时间序列得分 {time_series_score:.2f}", f"事件得分 {event_score:.2f}", f"市场状态 {market_regime}"]
        if negative_event_veto: return FusedSignal(raw, gated, min(gated, 0), 0, "blocked", True, veto_reason or "重大负面事件否决", components, reasons+[veto_reason or "重大负面事件否决"])
        signal = "buy" if gated >= .65 else "watch" if gated >= .50 else "reduce" if gated < .35 else "hold"
        position = self.config.regime_position_limits[market_regime] if signal == "buy" else 0
        return FusedSignal(raw, gated, gated, position, signal, False, None, components, reasons)

"""Rank-buffered portfolio recommendations with explicit constraints."""

from __future__ import annotations

from dataclasses import asdict

from finance_analysis.quant.config import PortfolioConfig


class PortfolioBuilder:
    def __init__(self, config: PortfolioConfig | None = None): self.config = config or PortfolioConfig()

    def build(self, signals: list[dict], max_equity_exposure: float, current_weights: dict[str,float] | None = None) -> dict:
        current_weights = current_weights or {}; ordered = sorted(signals, key=lambda item: item["final_score"], reverse=True)
        eligible = [item for item in ordered if not item.get("vetoed") and item.get("has_sufficient_data", True) and item.get("liquidity", self.config.minimum_liquidity) >= self.config.minimum_liquidity]
        buys = eligible[:self.config.buy_top_k]; watch_codes = {item["code"] for item in eligible[:self.config.watch_top_k]}
        selected_codes = {item["code"] for item in buys}
        for item in eligible:
            if current_weights.get(item["code"],0)>0 and item.get("rank",999)<=self.config.hold_rank_threshold: selected_codes.add(item["code"])
        raw_weights = self._weights([item for item in eligible if item["code"] in selected_codes], max_equity_exposure)
        sector_totals, new_exposure, turnover, rows = {}, 0.0, 0.0, []
        for rank, item in enumerate(ordered,1):
            code, sector = item["code"], item.get("sector_key") or "unknown"; current = float(current_weights.get(code,0)); target = raw_weights.get(code,0)
            constraints=[]
            allowed_sector=max(0,self.config.sector_max_weight-sector_totals.get(sector,0)); target=min(target,allowed_sector,self.config.single_stock_max_weight,max_equity_exposure)
            if item.get("vetoed") or not item.get("has_sufficient_data",True): target=0; constraints.append("veto_or_insufficient_data")
            increase=max(0,target-current)
            if new_exposure+increase>self.config.maximum_daily_new_exposure: target=current+max(0,self.config.maximum_daily_new_exposure-new_exposure); constraints.append("daily_new_exposure")
            change=target-current
            if turnover+abs(change)>self.config.maximum_daily_turnover: target=current; change=0; constraints.append("daily_turnover")
            new_exposure+=max(0,change); turnover+=abs(change); sector_totals[sector]=sector_totals.get(sector,0)+target
            if item.get("vetoed"): action="blocked"
            elif target>current and current==0: action="buy"
            elif target>current: action="increase"
            elif target==current and target>0: action="hold"
            elif target<current and target>0: action="reduce"
            elif current>0 and rank>self.config.sell_rank_threshold: action="sell"
            elif code in watch_codes: action="watch"
            else: continue
            rows.append({**item,"rank":rank,"action":action,"current_weight":current,"target_weight":target,"weight_change":target-current,"constraints":constraints})
        target_exposure=sum(item["target_weight"] for item in rows)
        return {"items":rows,"target_equity_exposure":target_exposure,"sector_exposure":sector_totals,"warnings":[],"config":asdict(self.config)}

    def _weights(self, selected: list[dict], exposure: float) -> dict[str,float]:
        if not selected: return {}
        cap=min(exposure,self.config.single_stock_max_weight*len(selected))
        if self.config.weighting=="equal_weight": return {item["code"]:cap/len(selected) for item in selected}
        if self.config.weighting=="score_weight":
            total=sum(max(0,item["final_score"]) for item in selected)
            return {item["code"]:(cap*max(0,item["final_score"])/total if total else cap/len(selected)) for item in selected}
        raise ValueError(f"Unknown weighting: {self.config.weighting}")

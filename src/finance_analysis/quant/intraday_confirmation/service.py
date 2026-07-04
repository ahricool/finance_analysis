"""Point-in-time minute-bar entry confirmation; no network fallback."""

from __future__ import annotations

import numpy as np
import pandas as pd

from finance_analysis.quant.config import IntradayConfig


class IntradayConfirmationService:
    def __init__(self, config: IntradayConfig | None = None): self.config=config or IntradayConfig()

    def evaluate(self, code: str, bars: pd.DataFrame, market_bars: pd.DataFrame, sector_bars: pd.DataFrame, evaluated_at, vetoed: bool=False) -> dict:
        # A bar stamped 10:00 is incomplete at 10:00 and therefore excluded.
        own=bars[pd.to_datetime(bars.bar_time,utc=True)<pd.Timestamp(evaluated_at)].sort_values("bar_time")
        market=market_bars[pd.to_datetime(market_bars.bar_time,utc=True)<pd.Timestamp(evaluated_at)].sort_values("bar_time")
        sector=sector_bars[pd.to_datetime(sector_bars.bar_time,utc=True)<pd.Timestamp(evaluated_at)].sort_values("bar_time")
        if min(len(own),len(market),len(sector))<self.config.minimum_bars:
            return {"code":code,"decision":"insufficient_data","confidence":0.0,"reasons":["已完成分钟K线不足"],"features":{"available_bars":len(own)}}
        volume=own.volume.astype(float); vwap=(own.close*volume).cumsum()/volume.cumsum().replace(0,np.nan); price=float(own.close.iloc[-1])
        market_return=float(market.close.iloc[-1]/market.open.iloc[0]-1); sector_return=float(sector.close.iloc[-1]/sector.open.iloc[0]-1); own_return=float(price/own.open.iloc[0]-1)
        features={"price":price,"vwap":float(vwap.iloc[-1]),"price_vs_vwap":float(price/vwap.iloc[-1]-1),"vwap_slope":float(vwap.iloc[-1]/vwap.iloc[-min(10,len(vwap))]-1),
                  "first_30m_return":float(own.close.iloc[29]/own.open.iloc[0]-1),"intraday_high_drawdown":float(price/own.high.cummax().iloc[-1]-1),
                  "volume_ratio":float(volume.tail(5).mean()/volume.head(5).mean()) if volume.head(5).mean() else None,
                  "relative_strength_market":own_return-market_return,"relative_strength_sector":own_return-sector_return,
                  "opening_gap":None,"distance_from_open":own_return}
        if vetoed: decision,reasons="reject",["重大负面事件仍处于否决状态"]
        elif features["distance_from_open"]>self.config.maximum_opening_gap: decision,reasons="wait",["开盘涨幅过大，等待回落确认"]
        elif features["intraday_high_drawdown"]<-self.config.maximum_drawdown: decision,reasons="reject",["盘中强转弱"]
        else:
            checks=[features["price_vs_vwap"]>0,features["vwap_slope"]>=0,features["relative_strength_market"]>0,features["relative_strength_sector"]>0,(features["volume_ratio"] or 0)>=self.config.minimum_volume_ratio]
            decision="confirm" if sum(checks)>=4 else "wait"; reasons=[name for passed,name in zip(checks,["价格位于VWAP上方","VWAP斜率非负","相对市场转强","相对行业转强","成交量达到阈值"]) if passed]
        confidence=min(1.0,len(reasons)/5+(.3 if decision=="confirm" else 0))
        return {"code":code,"decision":decision,"confidence":confidence,"reasons":reasons,"features":features}

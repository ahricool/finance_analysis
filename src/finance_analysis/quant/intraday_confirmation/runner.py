"""Database-backed minute confirmation runner with no network fallback."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
from sqlalchemy import select

from finance_analysis.database.models.quant import PortfolioRecommendation, PortfolioRecommendationItem, QuantUniverseMember
from finance_analysis.database.models.stock import MarketDataSymbol, StockMinute
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.cache import QuantLatestCache, cache_keys
from finance_analysis.quant.intraday_confirmation.service import IntradayConfirmationService


class IntradayConfirmationRunner:
    def __init__(self,repository=None,cache=None): self.repository=repository or QuantRepository();self.cache=cache or QuantLatestCache()

    def run(self,trade_date:date,evaluated_at:datetime|None=None)->dict:
        evaluated_at=evaluated_at or datetime.now(timezone.utc)
        with self.repository.db.get_session() as session:
            recommendation=session.execute(select(PortfolioRecommendation).where(PortfolioRecommendation.trade_date<trade_date)
                .order_by(PortfolioRecommendation.trade_date.desc()).limit(1)).scalar_one_or_none()
            if not recommendation: return {"trade_date":str(trade_date),"count":0,"status":"insufficient_data","reason":"No previous recommendation"}
            items=list(session.execute(select(PortfolioRecommendationItem).where(PortfolioRecommendationItem.recommendation_id==recommendation.id,
                PortfolioRecommendationItem.action.in_(("buy","increase","watch")))).scalars())
            mappings={row.symbol_id:row.sector_benchmark_code for row in session.execute(select(QuantUniverseMember).where(
                QuantUniverseMember.universe_id==recommendation.universe_id)).scalars()}
            candidates=[(item.id,item.symbol_id,item.code,item.action,item.constraints,mappings.get(item.symbol_id)) for item in items]
        values=[];service=IntradayConfirmationService()
        for item_id,symbol_id,code,_,constraints,sector_code in candidates:
            own=self._bars(code,trade_date,evaluated_at);market=self._bars("QQQ.US",trade_date,evaluated_at);sector=self._bars(sector_code or "QQQ.US",trade_date,evaluated_at)
            result=service.evaluate(code,own,market,sector,evaluated_at,vetoed="veto_or_insufficient_data" in (constraints or {}).get("applied",[]))
            feature=result["features"]
            values.append({"trade_date":trade_date,"symbol_id":symbol_id,"code":code,"recommendation_item_id":item_id,"evaluated_at":evaluated_at,
                "decision":result["decision"],"confidence":result["confidence"],"price":feature.get("price"),"vwap":feature.get("vwap"),
                "price_vs_vwap":feature.get("price_vs_vwap"),"vwap_slope":feature.get("vwap_slope"),"first_30m_return":feature.get("first_30m_return"),
                "intraday_high_drawdown":feature.get("intraday_high_drawdown"),"volume_ratio":feature.get("volume_ratio"),
                "relative_strength_market":feature.get("relative_strength_market"),"relative_strength_sector":feature.get("relative_strength_sector"),
                "reasons":result["reasons"],"features":feature})
            self.cache.set(cache_keys("US",code=code)["intraday"],result)
        self.repository.save_confirmations(values)
        return {"trade_date":str(trade_date),"count":len(values),"decisions":{state:sum(item["decision"]==state for item in values) for state in ("confirm","wait","reject","insufficient_data")}}

    def _bars(self,code:str,start_date:date,evaluated_at:datetime)->pd.DataFrame:
        start=datetime.combine(start_date,time.min,tzinfo=timezone.utc);end=min(evaluated_at,start+timedelta(days=2))
        with self.repository.db.get_session() as session:
            rows=session.execute(select(StockMinute.bar_time,StockMinute.open,StockMinute.high,StockMinute.low,StockMinute.close,StockMinute.volume,StockMinute.amount)
                .join(MarketDataSymbol,MarketDataSymbol.id==StockMinute.symbol_id).where(MarketDataSymbol.code==code,StockMinute.bar_time>=start,StockMinute.bar_time<end)
                .order_by(StockMinute.bar_time)).all()
        return pd.DataFrame(rows,columns=["bar_time","open","high","low","close","volume","amount"])

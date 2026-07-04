"""Compute and persist one point-in-time daily research snapshot."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from finance_analysis.database.models.stock import MarketDataSymbol, StockDaily
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.events.scoring import score_events
from finance_analysis.quant.exceptions import BenchmarkDataMissingError, FeatureDataMissingError
from finance_analysis.quant.features.daily import add_relative_strength, build_daily_features
from finance_analysis.quant.regime.service import MarketRegimeService
from finance_analysis.quant.sectors.service import SectorRegimeService


class DailyResearchService:
    def __init__(self, repository=None): self.repository=repository or QuantRepository(); self.config=get_quant_config()

    def run(self, market: str, universe_key: str, trade_date: date) -> dict:
        universe=self.repository.get_universe(universe_key)
        if not universe: raise ValueError(f"Unknown universe {universe_key}")
        members=self.repository.active_members(universe.id,trade_date)
        if not members: raise FeatureDataMissingError(f"No active universe members for {trade_date}")
        codes={symbol.code for _,symbol in members}; benchmarks={"QQQ.US","SPY.US","SOXX.US",universe.benchmark_code}
        benchmarks.update(member.sector_benchmark_code for member,_ in members); benchmarks.discard(None)
        frames=self._load(codes|benchmarks,trade_date-timedelta(days=500),trade_date)
        missing={code for code in benchmarks if code not in frames or len(frames[code])<61}
        if missing: raise BenchmarkDataMissingError(f"Missing benchmark history: {sorted(missing)}")
        stale={code for code in benchmarks if pd.Timestamp(frames[code]["date"].iloc[-1]).date()!=trade_date}
        if stale: raise BenchmarkDataMissingError(f"Benchmark data is not ready for {trade_date}: {sorted(stale)}")
        member_frames={symbol.code:frames[symbol.code] for _,symbol in members if symbol.code in frames and len(frames[symbol.code])>=61}
        if not member_frames: raise FeatureDataMissingError("No universe member has sufficient daily history")
        market_result=MarketRegimeService(self.config.regime).calculate(frames["QQQ.US"],frames["SPY.US"],frames["SOXX.US"],member_frames)
        regime=self.repository.save_market_regime({"market":market,"trade_date":trade_date,"model_version":self.config.regime_model_version,
            "regime":market_result.regime,"market_score":market_result.market_score,"max_equity_exposure":market_result.max_equity_exposure,
            "sector_permissions":market_result.sector_permissions,"features":market_result.features,"reasons":market_result.reasons})
        sector_inputs={}
        for member,symbol in members:
            if symbol.code not in member_frames or not member.sector_benchmark_code or member.sector_benchmark_code not in frames: continue
            entry=sector_inputs.setdefault(member.sector_key or "unknown",[member.sector_benchmark_code,frames[member.sector_benchmark_code],{}]);entry[2][symbol.code]=member_frames[symbol.code]
        sectors=SectorRegimeService().rank({key:(value[0],value[1],value[2]) for key,value in sector_inputs.items()},frames["QQQ.US"],market_result.regime)
        self.repository.save_sector_regimes([{"market":market,"trade_date":trade_date,"model_version":self.config.sector_model_version,**row} for row in sectors])
        sector_scores={row["sector_key"]:row["sector_score"] for row in sectors}; daily_values=[]; event_values=[]
        cutoff=datetime.combine(trade_date,time(16,0),ZoneInfo("America/New_York"))
        for member,symbol in members:
            bars=member_frames.get(symbol.code)
            if bars is None: continue
            sector_bars=frames.get(member.sector_benchmark_code)
            if sector_bars is None: continue
            features=add_relative_strength(build_daily_features(bars),frames["QQQ.US"],sector_bars).iloc[-1]
            events=self.repository.available_events(symbol.id,cutoff,cutoff-timedelta(days=90)); event=score_events(events,cutoff)
            explicit={key:(None if pd.isna(features.get(key)) else float(features[key])) for key in (
                "ret_1d","ret_5d","ret_20d","ret_60d","price_ma20_ratio","price_ma60_ratio","volume_ratio_5d","atr_14","realized_vol_20d","distance_from_20d_high","gap_return","rsi_14","relative_5d_to_market","relative_20d_to_market","relative_5d_to_sector","relative_20d_to_sector")}
            daily_values.append({"trade_date":trade_date,"symbol_id":symbol.id,"feature_version":self.config.feature_version,**explicit,
                "market_score":market_result.market_score,"sector_score":sector_scores.get(member.sector_key),"event_score":event["event_score"],"features":{"sector_key":member.sector_key,"price_mode":"raw"}})
            event_values.append({"trade_date":trade_date,"symbol_id":symbol.id,"feature_version":self.config.event_feature_version,
                "positive_event_count_3d":event["positive_event_count_3d"],"negative_event_count_3d":event["negative_event_count_3d"],
                "event_score":event["event_score"],"negative_event_veto":event["negative_event_veto"],"feature_payload":{"components":event["components"]}})
        self.repository.save_daily_features(daily_values);self.repository.save_event_features(event_values)
        return {"market_regime":regime,"sectors":sectors,"feature_count":len(daily_values),"warnings":["price_mode=raw"]}

    def _load(self,codes:set[str],start:date,end:date)->dict[str,pd.DataFrame]:
        with self.repository.db.get_session() as session:
            rows=session.execute(select(MarketDataSymbol.code,StockDaily.date,StockDaily.open,StockDaily.high,StockDaily.low,StockDaily.close,StockDaily.volume,StockDaily.amount)
                .join(StockDaily,StockDaily.symbol_id==MarketDataSymbol.id).where(MarketDataSymbol.code.in_(codes),StockDaily.date.between(start,end)).order_by(MarketDataSymbol.code,StockDaily.date)).all()
        frame=pd.DataFrame(rows,columns=["code","date","open","high","low","close","volume","amount"])
        return {code:group.drop(columns="code").reset_index(drop=True) for code,group in frame.groupby("code")}

"""Business orchestration for Qlib training and daily ranking."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, timedelta

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
from finance_analysis.quant.cache import QuantLatestCache, cache_keys
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.datasets.qlib_adapter import QlibAdapter
from finance_analysis.quant.exceptions import ModelNotPublishedError, QuantDatasetMissingError
from finance_analysis.quant.features.service import DailyResearchService
from finance_analysis.quant.portfolio.builder import PortfolioBuilder
from finance_analysis.quant.signals.fusion import SignalFusion

logger = logging.getLogger(__name__)


class QuantTrainingPipeline:
    def __init__(self, repository=None, exporter=None, qlib=None):
        self.repository=repository or QuantRepository(); self.exporter=exporter or QlibDatasetExporter(self.repository); self.qlib=qlib or QlibAdapter()

    def run(self, run_id: int) -> dict:
        run=self.repository.get_model_run(run_id)
        if not run: raise ValueError(f"Unknown model run {run_id}")
        self.repository.update_model_run(run_id,status="training",progress=5,started_at=utc_now(),error=None)
        try:
            dataset=self.repository.get_dataset(run.dataset_snapshot_id) if run.dataset_snapshot_id else None
            if not dataset or dataset.status!="ready": raise QuantDatasetMissingError("A ready dataset snapshot is required")
            self.repository.update_model_run(run_id,progress=25)
            result=self.qlib.train({"dataset_uri":dataset.artifact_uri,"model_key":run.model_key,"model_version":run.model_version,
                "parameters":run.parameters,"split_config":run.split_config,"feature_config":run.feature_config,"target_config":run.target_config})
            self.repository.update_model_run(run_id,status="candidate",progress=100,metrics=result.get("metrics",{}),
                feature_importance=result.get("feature_importance",{}),artifact_uri=result.get("artifact_uri"),
                artifact_digest=result.get("artifact_digest"),artifact_size=result.get("artifact_size"),warnings=result.get("warnings",[]),finished_at=utc_now())
            return {"model_run_id":run_id,"model_key":run.model_key,"status":"candidate","rank_ic":result.get("metrics",{}).get("rank_ic"),
                    "top10_excess_return_pct":result.get("metrics",{}).get("top10_excess_return_pct")}
        except Exception as exc:
            self.repository.update_model_run(run_id,status="failed",progress=100,error=str(exc),finished_at=utc_now()); raise


class QuantDailyPipeline:
    def __init__(self,repository=None,qlib=None,cache=None,exporter=None):
        self.repository=repository or QuantRepository(); self.qlib=qlib or QlibAdapter(); self.cache=cache or QuantLatestCache(); self.exporter=exporter or QlibDatasetExporter(self.repository)

    def run(self, market: str="US", universe_key: str="us_ai_semiconductor", trade_date: date | None=None) -> dict:
        trade_date=trade_date or date.today(); universe=self.repository.get_universe(universe_key)
        if not universe: raise ValueError(f"Unknown universe {universe_key}")
        model=self.repository.production_model(market,"cross_section_lgbm")
        if not model: raise ModelNotPublishedError("No production cross_section_lgbm model")
        if not model.artifact_uri: raise ModelNotPublishedError("Production model has no artifact")
        time_series_model=self.repository.production_model(market,"time_series_lgbm")
        if not time_series_model or not time_series_model.artifact_uri: raise ModelNotPublishedError("No production time_series_lgbm model")
        research=DailyResearchService(self.repository).run(market,universe_key,trade_date); regime=research["market_regime"]
        prediction_dataset=self.exporter.export(market,universe_key,trade_date-timedelta(days=500),trade_date)
        request={"dataset_uri":prediction_dataset.artifact_uri,"trade_date":str(trade_date),"universe":universe_key}
        response=self.qlib.predict({"artifact_uri":model.artifact_uri,**request})
        time_series_response=self.qlib.predict({"artifact_uri":time_series_model.artifact_uri,**request})
        time_series_by_code={item["code"]:item["normalized_score"] for item in time_series_response.get("predictions",[])}
        config=get_quant_config(); context=self.repository.feature_context(trade_date,config.feature_version,config.event_feature_version); member_codes={symbol.code for _,symbol in self.repository.active_members(universe.id,trade_date)}
        fusion=SignalFusion(); signal_values=[]; public=[]
        for prediction in response.get("predictions",[]):
            if prediction["code"] not in member_codes: continue
            symbol = MarketDataSymbolRepository().get_by_code(prediction["code"])
            if symbol is None:
                logger.warning("Quant prediction skipped: unknown code=%s trade_date=%s", prediction["code"], trade_date)
                continue
            prediction["symbol_id"] = symbol.id
            feature=context.get(symbol.id,{})
            prediction.update({"time_series_score":time_series_by_code.get(prediction["code"]),"event_score":feature.get("event_score",0),
                "sector_score":feature.get("sector_score"),"sector_key":feature.get("sector_key"),"negative_event_veto":feature.get("negative_event_veto",False)})
            if prediction["time_series_score"] is None: raise QuantDatasetMissingError(f"Time-series prediction missing for {prediction['code']}")
            fused=fusion.fuse(float(prediction["normalized_score"]),float(prediction["time_series_score"]),float(prediction["event_score"]),regime.regime,
                market_score=regime.market_score,sector_score=prediction.get("sector_score"),risk_penalty=float(prediction.get("risk_penalty",0)),
                negative_event_veto=bool(prediction.get("negative_event_veto")),veto_reason=prediction.get("veto_reason"))
            item={**prediction,**asdict(fused)}; public.append(item)
            signal_values.append({"trade_date":trade_date,"symbol_id":prediction["symbol_id"],"code":prediction["code"],"market":market,"universe_id":universe.id,
                "model_version":model.model_version,"market_score":regime.market_score,"sector_score":prediction.get("sector_score"),"event_score":prediction.get("event_score"),
                "time_series_score":prediction.get("time_series_score"),"cross_section_score":prediction["normalized_score"],"risk_penalty":prediction.get("risk_penalty",0),
                "raw_final_score":fused.raw_final_score,"gated_final_score":fused.gated_final_score,"final_score":fused.final_score,
                "universe_rank":prediction.get("universe_rank"),"sector_rank":prediction.get("sector_rank"),"predicted_return":prediction.get("predicted_return"),
                "signal":fused.signal,"target_position":fused.target_position,"vetoed":fused.vetoed,"veto_reason":fused.veto_reason,"reasons":fused.reasons,"score_components":fused.score_components})
        self.repository.replace_signals(trade_date,model.model_version,signal_values)
        portfolio=PortfolioBuilder().build(public,regime.max_equity_exposure)
        recommendation=self.repository.save_portfolio({"trade_date":trade_date,"market":market,"universe_id":universe.id,"model_version":model.model_version,
            "market_regime_id":regime.id,"status":"ready","max_equity_exposure":regime.max_equity_exposure,"target_equity_exposure":portfolio["target_equity_exposure"],
            "config":portfolio["config"],"summary":{"sector_exposure":portfolio["sector_exposure"]},"warnings":portfolio["warnings"]},[
                {"symbol_id":item["symbol_id"],"code":item["code"],"sector_key":item.get("sector_key"),"rank":item["rank"],"previous_rank":item.get("previous_rank"),
                 "action":item["action"],"current_weight":item["current_weight"],"target_weight":item["target_weight"],"weight_change":item["weight_change"],
                 "final_score":item["final_score"],"predicted_return":item.get("predicted_return"),"signal":item["signal"],"reasons":item["reasons"],"constraints":{"applied":item["constraints"]}}
                for item in portfolio["items"]])
        warning=[]
        if not self.cache.set(cache_keys(market,universe_key)["ranking"],public): warning.append("Redis ranking cache write failed")
        if not self.cache.set(cache_keys(market,universe_key)["portfolio"],{"id":recommendation.id,"trade_date":trade_date}): warning.append("Redis portfolio cache write failed")
        return {"trade_date":str(trade_date),"market":market,"universe":universe_key,"signal_count":len(public),"buy_count":sum(i["signal"]=="buy" for i in public),
                "portfolio_recommendation_id":recommendation.id,"market_regime":regime.regime,"warnings":warning}

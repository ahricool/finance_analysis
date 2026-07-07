"""Business-side orchestration around JSON-only Qlib task results."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
from finance_analysis.market_review.trading_calendar import get_effective_trading_date
from finance_analysis.quant.cache import QuantLatestCache, cache_keys
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.exceptions import ModelNotPublishedError, QuantDatasetMissingError
from finance_analysis.quant.features.service import DailyResearchService
from finance_analysis.quant.portfolio.builder import PortfolioBuilder
from finance_analysis.quant.signals.fusion import SignalFusion

logger = logging.getLogger(__name__)
PROTOCOL_VERSION = 1


class QuantTrainingPipeline:
    def __init__(self, repository: Any = None):
        self.repository = repository or QuantRepository()

    def prepare(self, run_id: int) -> dict[str, Any]:
        run = self.repository.get_model_run(run_id)
        if not run:
            raise ValueError(f"Unknown model run {run_id}")
        dataset = self.repository.get_dataset(run.dataset_snapshot_id) if run.dataset_snapshot_id else None
        if not dataset or dataset.status != "ready" or not dataset.artifact_uri:
            raise QuantDatasetMissingError("A ready dataset snapshot with an artifact is required")
        self.repository.update_model_run(
            run_id,
            status="training",
            progress=10,
            started_at=utc_now(),
            error=None,
        )
        return {
            "schema_version": PROTOCOL_VERSION,
            "model_run_id": run.id,
            "dataset_uri": dataset.artifact_uri,
            "model_key": run.model_key,
            "model_version": run.model_version,
            "parameters": run.parameters or {},
            "split_config": run.split_config or {},
            "feature_config": run.feature_config or {},
            "target_config": run.target_config or {},
        }

    def mark_dispatched(self, run_id: int, task_id: str) -> None:
        self.repository.update_model_run(run_id, task_id=task_id, progress=25)

    def finalize(self, run_id: int, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("schema_version") != PROTOCOL_VERSION:
            raise ValueError("Qlib result has an unsupported schema_version")
        if result.get("model_run_id") != run_id:
            raise ValueError("Qlib result model_run_id does not match callback")
        run = self.repository.get_model_run(run_id)
        if not run:
            raise ValueError(f"Unknown model run {run_id}")
        if result.get("model_key") != run.model_key:
            raise ValueError("Qlib result model_key does not match ModelRun")
        self.repository.update_model_run(
            run_id,
            status="candidate",
            progress=100,
            metrics=result.get("metrics", {}),
            feature_importance=result.get("feature_importance", {}),
            artifact_uri=result.get("artifact_uri"),
            artifact_digest=result.get("artifact_digest"),
            artifact_size=result.get("artifact_size"),
            warnings=result.get("warnings", []),
            error=None,
            finished_at=utc_now(),
        )
        return {
            "model_run_id": run_id,
            "model_key": run.model_key,
            "status": "candidate",
            "rank_ic": result.get("metrics", {}).get("rank_ic"),
            "top10_excess_return_pct": result.get("metrics", {}).get("top10_excess_return_pct"),
        }

    def fail(self, run_id: int, reason: str) -> dict[str, Any]:
        self.repository.update_model_run(
            run_id,
            status="failed",
            progress=100,
            error=reason[:4000],
            finished_at=utc_now(),
        )
        return {"model_run_id": run_id, "status": "failed", "error": reason[:4000]}


class QuantDailyPipeline:
    def __init__(self, repository: Any = None, cache: Any = None, exporter: Any = None):
        self.repository = repository or QuantRepository()
        self.cache = cache or QuantLatestCache()
        self.exporter = exporter or QlibDatasetExporter(self.repository)

    def prepare(
        self,
        market: str = "US",
        universe_key: str = "us_ai_semiconductor",
        trade_date: date | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        market = market.upper()
        if trade_date is None:
            if market != "US":
                raise ValueError("An explicit trade_date is required for non-US quant pipelines")
            trade_date = get_effective_trading_date("us")
        universe = self.repository.get_universe(universe_key)
        if not universe:
            raise ValueError(f"Unknown universe {universe_key}")
        cross_section = self._production_model(market, "cross_section_lgbm")
        time_series = self._production_model(market, "time_series_lgbm")
        research = DailyResearchService(self.repository).run(market, universe_key, trade_date)
        regime = research["market_regime"]
        prediction_dataset = self.exporter.export(
            market,
            universe_key,
            trade_date - timedelta(days=500),
            trade_date,
        )
        common = {
            "schema_version": PROTOCOL_VERSION,
            "dataset_uri": prediction_dataset.artifact_uri,
            "trade_date": str(trade_date),
        }
        requests = [
            {
                **common,
                "model_run_id": cross_section.id,
                "model_key": cross_section.model_key,
                "artifact_uri": cross_section.artifact_uri,
            },
            {
                **common,
                "model_run_id": time_series.id,
                "model_key": time_series.model_key,
                "artifact_uri": time_series.artifact_uri,
            },
        ]
        context = {
            "schema_version": PROTOCOL_VERSION,
            "trade_date": str(trade_date),
            "market": market,
            "universe_key": universe_key,
            "universe_id": universe.id,
            "cross_section_model_run_id": cross_section.id,
            "cross_section_model_version": cross_section.model_version,
            "time_series_model_run_id": time_series.id,
            "regime": {
                "id": regime.id,
                "regime": regime.regime,
                "market_score": regime.market_score,
                "max_equity_exposure": regime.max_equity_exposure,
            },
        }
        return requests, context

    def finalize(self, responses: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
        if context.get("schema_version") != PROTOCOL_VERSION:
            raise ValueError("Daily callback context has unsupported schema_version")
        trade_date = date.fromisoformat(context["trade_date"])
        market = context["market"]
        universe_key = context["universe_key"]
        universe = self.repository.get_universe(universe_key)
        if not universe or universe.id != context["universe_id"]:
            raise ValueError("Daily callback universe no longer matches")
        by_model = {response.get("model_key"): response for response in responses}
        response = by_model.get("cross_section_lgbm")
        time_series_response = by_model.get("time_series_lgbm")
        if response is None or time_series_response is None:
            raise QuantDatasetMissingError("Both Qlib prediction results are required")
        for item in (response, time_series_response):
            if item.get("schema_version") != PROTOCOL_VERSION or item.get("trade_date") != str(trade_date):
                raise ValueError("Qlib prediction result protocol or trade_date mismatch")
        time_series_by_code = {
            item["code"]: item["normalized_score"] for item in time_series_response.get("predictions", [])
        }
        config = get_quant_config()
        feature_context = self.repository.feature_context(
            trade_date, config.feature_version, config.event_feature_version
        )
        member_codes = {symbol.code for _, symbol in self.repository.active_members(universe.id, trade_date)}
        regime = context["regime"]
        fusion = SignalFusion()
        signal_values: list[dict[str, Any]] = []
        public: list[dict[str, Any]] = []
        symbol_repository = MarketDataSymbolRepository()
        for prediction in response.get("predictions", []):
            if prediction["code"] not in member_codes:
                continue
            symbol = symbol_repository.get_by_code(prediction["code"])
            if symbol is None:
                logger.warning(
                    "Quant prediction skipped: unknown code=%s trade_date=%s",
                    prediction["code"],
                    trade_date,
                )
                continue
            prediction["symbol_id"] = symbol.id
            feature = feature_context.get(symbol.id, {})
            prediction.update(
                {
                    "time_series_score": time_series_by_code.get(prediction["code"]),
                    "event_score": feature.get("event_score", 0),
                    "sector_score": feature.get("sector_score"),
                    "sector_key": feature.get("sector_key"),
                    "negative_event_veto": feature.get("negative_event_veto", False),
                }
            )
            if prediction["time_series_score"] is None:
                raise QuantDatasetMissingError(f"Time-series prediction missing for {prediction['code']}")
            fused = fusion.fuse(
                float(prediction["normalized_score"]),
                float(prediction["time_series_score"]),
                float(prediction["event_score"]),
                regime["regime"],
                market_score=regime["market_score"],
                sector_score=prediction.get("sector_score"),
                risk_penalty=float(prediction.get("risk_penalty", 0)),
                negative_event_veto=bool(prediction.get("negative_event_veto")),
                veto_reason=prediction.get("veto_reason"),
            )
            item = {**prediction, **asdict(fused)}
            public.append(item)
            signal_values.append(
                {
                    "trade_date": trade_date,
                    "symbol_id": prediction["symbol_id"],
                    "code": prediction["code"],
                    "market": market,
                    "universe_id": universe.id,
                    "model_version": context["cross_section_model_version"],
                    "market_score": regime["market_score"],
                    "sector_score": prediction.get("sector_score"),
                    "event_score": prediction.get("event_score"),
                    "time_series_score": prediction.get("time_series_score"),
                    "cross_section_score": prediction["normalized_score"],
                    "risk_penalty": prediction.get("risk_penalty", 0),
                    "raw_final_score": fused.raw_final_score,
                    "gated_final_score": fused.gated_final_score,
                    "final_score": fused.final_score,
                    "universe_rank": prediction.get("universe_rank"),
                    "sector_rank": prediction.get("sector_rank"),
                    "predicted_return": prediction.get("predicted_return"),
                    "signal": fused.signal,
                    "target_position": fused.target_position,
                    "vetoed": fused.vetoed,
                    "veto_reason": fused.veto_reason,
                    "reasons": fused.reasons,
                    "score_components": fused.score_components,
                }
            )
        self.repository.replace_signals(trade_date, context["cross_section_model_version"], signal_values)
        portfolio = PortfolioBuilder().build(public, regime["max_equity_exposure"])
        recommendation = self.repository.save_portfolio(
            {
                "trade_date": trade_date,
                "market": market,
                "universe_id": universe.id,
                "model_version": context["cross_section_model_version"],
                "market_regime_id": regime["id"],
                "status": "ready",
                "max_equity_exposure": regime["max_equity_exposure"],
                "target_equity_exposure": portfolio["target_equity_exposure"],
                "config": portfolio["config"],
                "summary": {"sector_exposure": portfolio["sector_exposure"]},
                "warnings": portfolio["warnings"],
            },
            [
                {
                    "symbol_id": item["symbol_id"],
                    "code": item["code"],
                    "sector_key": item.get("sector_key"),
                    "rank": item["rank"],
                    "previous_rank": item.get("previous_rank"),
                    "action": item["action"],
                    "current_weight": item["current_weight"],
                    "target_weight": item["target_weight"],
                    "weight_change": item["weight_change"],
                    "final_score": item["final_score"],
                    "predicted_return": item.get("predicted_return"),
                    "signal": item["signal"],
                    "reasons": item["reasons"],
                    "constraints": {"applied": item["constraints"]},
                }
                for item in portfolio["items"]
            ],
        )
        warnings: list[str] = []
        keys = cache_keys(market, universe_key)
        if not self.cache.set(keys["ranking"], public):
            warnings.append("Redis ranking cache write failed")
        if not self.cache.set(keys["portfolio"], {"id": recommendation.id, "trade_date": trade_date}):
            warnings.append("Redis portfolio cache write failed")
        return {
            "trade_date": str(trade_date),
            "market": market,
            "universe": universe_key,
            "signal_count": len(public),
            "buy_count": sum(item["signal"] == "buy" for item in public),
            "portfolio_recommendation_id": recommendation.id,
            "market_regime": regime["regime"],
            "warnings": warnings,
        }

    def _production_model(self, market: str, model_key: str) -> Any:
        model = self.repository.production_model(market, model_key)
        if not model or not model.artifact_uri:
            raise ModelNotPublishedError(f"No production {model_key} model artifact")
        return model

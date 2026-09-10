"""Business-side orchestration around JSON-only Qlib task results."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import date
from typing import Any

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.repositories.quant import QuantRepository  # pragma: allowlist secret
from finance_analysis.database.repositories.stock import InstrumentRepository  # pragma: allowlist secret
from finance_analysis.market_review.trading_calendar import get_effective_trading_date  # pragma: allowlist secret
from finance_analysis.quant.config import get_quant_config  # pragma: allowlist secret
from finance_analysis.quant.datasets.artifact_store import ArtifactStore  # pragma: allowlist secret
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter  # pragma: allowlist secret
from finance_analysis.quant.exceptions import (  # pragma: allowlist secret
    FeatureDataMissingError,
    ModelNotPublishedError,
    PredictionFailedError,
    QuantDatasetMissingError,
)
from finance_analysis.quant.features.service import DailyResearchService  # pragma: allowlist secret
from finance_analysis.quant.lookback import prediction_dataset_start  # pragma: allowlist secret
from finance_analysis.quant.markets import (  # pragma: allowlist secret
    get_quant_market_config,
    get_universe_codes,
    validate_universe_for_market,
)
from finance_analysis.quant.models import CROSS_SECTION_MODEL_KEY, TIME_SERIES_MODEL_KEY  # pragma: allowlist secret
from finance_analysis.quant.portfolio.builder import PortfolioBuilder  # pragma: allowlist secret
from finance_analysis.quant.signals.fusion import SignalFusion  # pragma: allowlist secret
from finance_analysis.quant.targets import resolve_target_config, stored_target_matches_production  # pragma: allowlist secret

PROTOCOL_VERSION = 1
SUPPORTED_QLIB_FEATURE_CONFIG = {"base": "Alpha158"}
_PRIMARY_METRIC_KEYS = {
    CROSS_SECTION_MODEL_KEY: ("daily_rank_ic_mean", "icir", "top10_excess_return_pct"),
    TIME_SERIES_MODEL_KEY: ("roc_auc", "balanced_accuracy", "directional_hit_rate"),
}


class QuantTrainingPipeline:
    def __init__(self, repository: Any = None, artifact_store: Any = None):
        self.repository = repository or QuantRepository()
        self.artifact_store = artifact_store

    def _supported_run(self, run_id: int) -> Any:
        run = self.repository.get_model_run(run_id)
        if not run:
            raise ValueError(f"Unknown model run {run_id}")
        universe = self.repository.get_universe(run.universe_id)
        if not universe or universe.market != run.market:
            raise ValueError(f"Model run {run_id} is bound to an unavailable universe")
        validate_universe_for_market(run.market, universe.key)
        if not getattr(universe, "enabled", True):
            raise ValueError(f"Model run {run_id} is bound to an unavailable universe")
        return run

    def prepare(self, run_id: int) -> dict[str, Any]:
        run = self._supported_run(run_id)
        dataset = self.repository.get_dataset(run.dataset_snapshot_id) if run.dataset_snapshot_id else None
        if not dataset or dataset.status != "ready" or not dataset.artifact_uri:
            raise QuantDatasetMissingError("A ready dataset snapshot with an artifact is required")
        if dataset.market != run.market or dataset.universe_id != run.universe_id:
            raise QuantDatasetMissingError("Model run and dataset must use the same market and universe")
        universe_members = len(get_universe_codes(run.market))
        dataset_symbols = int(dataset.symbol_count or 0)
        coverage_ratio = dataset_symbols / universe_members if universe_members else 0.0
        minimum_coverage = get_quant_config().minimum_universe_coverage
        if coverage_ratio < minimum_coverage:
            raise QuantDatasetMissingError(
                f"Dataset universe coverage below minimum: symbols={dataset_symbols} "
                f"universe={universe_members} coverage={coverage_ratio:.2%} "
                f"minimum={minimum_coverage:.2%}"
            )
        (self.artifact_store or ArtifactStore()).resolve_uri(dataset.artifact_uri)
        split_config = run.split_config or {}
        target_config = resolve_target_config(
            run.model_key,
            run.target_config or {},
            int(split_config.get("prediction_horizon") or 5),
        )
        self.repository.update_model_run(
            run_id,
            status="training",
            progress=10,
            started_at=utc_now(),
            error=None,
            target_config=target_config,
        )
        return {
            "schema_version": PROTOCOL_VERSION,
            "model_run_id": run.id,
            "dataset_uri": dataset.artifact_uri,
            "model_key": run.model_key,
            "model_version": run.model_version,
            "market": run.market,
            "universe_id": run.universe_id,
            "parameters": run.parameters or {},
            "split_config": split_config,
            "feature_config": run.feature_config or {},
            "target_config": target_config,
        }

    def mark_dispatched(self, run_id: int, task_id: str) -> None:
        self.repository.update_model_run(run_id, task_id=task_id, progress=25)

    def finalize(self, run_id: int, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("schema_version") != PROTOCOL_VERSION:
            raise ValueError("Qlib result has an unsupported schema_version")
        if result.get("model_run_id") != run_id:
            raise ValueError("Qlib result model_run_id does not match callback")
        run = self._supported_run(run_id)
        if result.get("model_key") != run.model_key:
            raise ValueError("Qlib result model_key does not match ModelRun")
        metrics = result.get("metrics", {})
        self.repository.update_model_run(
            run_id,
            status="candidate",
            progress=100,
            metrics=metrics,
            feature_importance=result.get("feature_importance", {}),
            artifact_uri=result.get("artifact_uri"),
            artifact_digest=result.get("artifact_digest"),
            artifact_size=result.get("artifact_size"),
            warnings=result.get("warnings", []),
            error=None,
            finished_at=utc_now(),
        )
        summary = {key: metrics.get(key) for key in _PRIMARY_METRIC_KEYS.get(run.model_key, ())}
        return {"model_run_id": run_id, "model_key": run.model_key, "status": "candidate", **summary}

    def fail(self, run_id: int, reason: str) -> dict[str, Any]:
        self._supported_run(run_id)
        self.repository.update_model_run(
            run_id,
            status="failed",
            progress=100,
            error=reason[:4000],
            finished_at=utc_now(),
        )
        return {"model_run_id": run_id, "status": "failed", "error": reason[:4000]}


class QuantDailyPipeline:
    def __init__(
        self,
        repository: Any = None,
        exporter: Any = None,
        symbol_repository: Any = None,
        artifact_store: Any = None,
    ):
        self.repository = repository or QuantRepository()
        self.exporter = exporter or QlibDatasetExporter(self.repository)
        self.symbol_repository = symbol_repository or InstrumentRepository()
        self.artifact_store = artifact_store

    def prepare(
        self,
        market: str = "US",
        universe_key: str | None = None,
        trade_date: date | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        config = get_quant_market_config(market)
        quant_config = get_quant_config()
        market = config.market
        if trade_date is None:
            trade_date = get_effective_trading_date(config.calendar_market)
        universe_key = validate_universe_for_market(market, universe_key)
        cross_section, time_series = self._preflight_production_models(market)
        universe = self.repository.get_universe(universe_key)
        if not universe or universe.market != market or not getattr(universe, "enabled", True):
            raise ValueError(f"Supported {market} universe {universe_key} is not available")
        universe_codes = get_universe_codes(market)
        research = DailyResearchService(
            self.repository,
            symbol_repository=self.symbol_repository,
        ).run(market, universe_key, trade_date)
        eligible_codes = set(research["eligible_codes"])
        if not eligible_codes.issubset(universe_codes):
            raise FeatureDataMissingError("Daily research returned codes outside the fixed Quant Universe")
        available_codes = self.repository.daily_bar_codes(eligible_codes, trade_date)
        missing_codes = sorted(eligible_codes - available_codes)
        if missing_codes:
            raise FeatureDataMissingError(
                f"Missing rankable universe daily data for trade_date={trade_date}: {missing_codes}"
            )
        regime = research["market_regime"]
        prediction_dataset = self.exporter.export(
            market,
            universe_key,
            prediction_dataset_start(market, trade_date),
            trade_date,
            candidate_codes=eligible_codes,
        )
        if prediction_dataset is None or not prediction_dataset.artifact_uri:
            raise QuantDatasetMissingError(f"Prediction dataset artifact is unavailable for {trade_date}")
        payload = {
            "schema_version": PROTOCOL_VERSION,
            "dataset_uri": prediction_dataset.artifact_uri,
            "trade_date": str(trade_date),
            "cross_section": {
                "model_run_id": cross_section.id,
                "model_key": CROSS_SECTION_MODEL_KEY,
                "artifact_uri": cross_section.artifact_uri,
            },
            "time_series": {
                "model_run_id": time_series.id,
                "model_key": TIME_SERIES_MODEL_KEY,
                "artifact_uri": time_series.artifact_uri,
            },
        }
        lineage = {
            "cross_section_model_run_id": cross_section.id,
            "cross_section_model_version": cross_section.model_version,
            "time_series_model_run_id": time_series.id,
            "time_series_model_version": time_series.model_version,
            "regime_model_version": quant_config.regime_model_version,
            "fusion_version": quant_config.fusion_version,
            "portfolio_version": quant_config.portfolio_version,
            "feature_version": quant_config.feature_version,
            "dataset_uri": prediction_dataset.artifact_uri,
            "dataset_source_revision": getattr(prediction_dataset, "source_revision", None),
        }
        context = {
            "schema_version": PROTOCOL_VERSION,
            "trade_date": str(trade_date),
            "market": market,
            "universe_key": universe_key,
            "universe_id": universe.id,
            "cross_section_model_run_id": cross_section.id,
            "cross_section_model_version": cross_section.model_version,
            "time_series_model_run_id": time_series.id,
            "time_series_model_version": time_series.model_version,
            "expected_codes": sorted(eligible_codes),
            "runtime_context": research["runtime_context"],
            "lineage": lineage,
            "regime": {
                "id": regime.id,
                "regime": regime.regime,
                "market_score": regime.market_score,
                "max_equity_exposure": regime.max_equity_exposure,
            },
            "warnings": research.get("warnings", []),
            "coverage": research.get("coverage", {}),
        }
        return payload, context

    def finalize(self, result: dict[str, Any] | list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
        if context.get("schema_version") != PROTOCOL_VERSION:
            raise ValueError("Daily callback context has unsupported schema_version")
        trade_date = date.fromisoformat(context["trade_date"])
        market = context["market"]
        universe_key = validate_universe_for_market(market, context.get("universe_key"))
        universe = self.repository.get_universe(universe_key)
        if (
            not universe
            or universe.id != context["universe_id"]
            or universe.market != market
            or not getattr(universe, "enabled", True)
        ):
            raise ValueError("Daily callback universe no longer matches")
        responses = self._prediction_results(result, trade_date)
        by_model = {response.get("model_key"): response for response in responses}
        response = by_model.get(CROSS_SECTION_MODEL_KEY)
        time_series_response = by_model.get(TIME_SERIES_MODEL_KEY)
        if response is None or time_series_response is None:
            raise QuantDatasetMissingError("Both Qlib prediction results are required")
        for item in (response, time_series_response):
            if item.get("schema_version") != PROTOCOL_VERSION or item.get("trade_date") != str(trade_date):
                raise ValueError("Qlib prediction result protocol or trade_date mismatch")
        expected_model_runs = {
            CROSS_SECTION_MODEL_KEY: context["cross_section_model_run_id"],
            TIME_SERIES_MODEL_KEY: context["time_series_model_run_id"],
        }
        for model_key, item in by_model.items():
            if model_key in expected_model_runs and item.get("model_run_id") not in (
                None,
                expected_model_runs[model_key],
            ):
                raise ValueError(f"Qlib prediction result model_run_id mismatch for {model_key}")
        universe_codes = get_universe_codes(market)
        expected_codes = set(context.get("expected_codes") or universe_codes)
        if not expected_codes.issubset(universe_codes):
            raise ValueError(
                "Daily callback universe membership no longer matches; "
                f"expected={sorted(expected_codes)} fixed={sorted(universe_codes)}"
            )
        self._validate_prediction_coverage(response, expected_codes, trade_date)
        self._validate_prediction_coverage(time_series_response, expected_codes, trade_date)
        time_series_by_code = {item["code"]: item["normalized_score"] for item in time_series_response["predictions"]}
        regime = context["regime"]
        runtime_context = context.get("runtime_context") or {}
        lineage = dict(context.get("lineage") or {})
        fusion = SignalFusion()
        public: list[dict[str, Any]] = []
        for prediction in response.get("predictions", []):
            symbol = self.symbol_repository.get_by_code(prediction["code"])
            if symbol is None:
                raise FeatureDataMissingError(f"Prediction code has no canonical symbol: {prediction['code']}")
            prediction["instrument_id"] = symbol.id
            feature = runtime_context.get(prediction["code"])
            if feature is None:
                raise FeatureDataMissingError(f"Daily runtime context missing for {prediction['code']} on {trade_date}")
            required_metadata = (
                "has_sufficient_data",
                "liquidity",
                "risk_penalty",
                "close",
            )
            missing_metadata = [key for key in required_metadata if feature.get(key) is None]
            if missing_metadata:
                raise FeatureDataMissingError(
                    f"Daily feature metadata missing for {prediction['code']} on {trade_date}: " f"{missing_metadata}"
                )
            prediction.update(
                {
                    "time_series_score": time_series_by_code.get(prediction["code"]),
                    "has_sufficient_data": bool(feature["has_sufficient_data"]),
                    "liquidity": float(feature["liquidity"]),
                    "risk_penalty": float(feature["risk_penalty"]),
                    "close": float(feature["close"]),
                }
            )
            if prediction["time_series_score"] is None:
                raise QuantDatasetMissingError(f"Time-series prediction missing for {prediction['code']}")
            fused = fusion.fuse(
                float(prediction["normalized_score"]),
                float(prediction["time_series_score"]),
                regime["regime"],
                market_score=regime["market_score"],
                risk_penalty=float(prediction.get("risk_penalty", 0)),
            )
            score_components = {**fused.score_components, "lineage": lineage}
            item = {**prediction, **asdict(fused), "score_components": score_components}
            public.append(item)
        public.sort(key=lambda item: item["final_score"], reverse=True)
        for rank, item in enumerate(public, 1):
            item["universe_rank"] = rank
        signal_values = [
            {
                "trade_date": trade_date,
                "instrument_id": item["instrument_id"],
                "code": item["code"],
                "market": market,
                "universe_id": universe.id,
                "model_version": context["cross_section_model_version"],
                "market_score": regime["market_score"],
                "time_series_score": item["time_series_score"],
                "cross_section_score": item["normalized_score"],
                "risk_penalty": item["risk_penalty"],
                "final_score": item["final_score"],
                "universe_rank": item["universe_rank"],
                "predicted_return": item.get("predicted_return"),
                "signal": item["signal"],
                "reasons": item["reasons"],
                "score_components": item["score_components"],
            }
            for item in public
        ]
        portfolio = PortfolioBuilder().build(public, regime["max_equity_exposure"])
        warnings: list[str] = [*context.get("warnings", []), *portfolio["warnings"]]
        portfolio_values = {
            "trade_date": trade_date,
            "market": market,
            "universe_id": universe.id,
            "model_version": context["cross_section_model_version"],
            "market_regime_id": regime["id"],
            "status": "ready",
            "max_equity_exposure": regime["max_equity_exposure"],
            "target_equity_exposure": portfolio["target_equity_exposure"],
            "config": {**portfolio["config"], "version": get_quant_config().portfolio_version},
            "summary": {
                "coverage": context.get("coverage", {}),
                "lineage": lineage,
            },
            "warnings": warnings,
        }
        portfolio_items = [
            {
                "instrument_id": item["instrument_id"],
                "code": item["code"],
                "rank": item["rank"],
                "target_weight": item["target_weight"],
                "final_score": item["final_score"],
                "predicted_return": item.get("predicted_return"),
                "signal": item["signal"],
                "reasons": item["reasons"],
                "constraints": item["constraints"],
            }
            for item in portfolio["items"]
        ]
        recommendation = self.repository.replace_signals_and_save_portfolio(
            market,
            universe.id,
            trade_date,
            context["cross_section_model_version"],
            signal_values,
            portfolio_values,
            portfolio_items,
        )
        return {
            "trade_date": str(trade_date),
            "market": market,
            "universe": universe_key,
            "signal_count": len(public),
            "buy_count": sum(item["signal"] == "buy" for item in public),
            "portfolio_item_count": len(portfolio["items"]),
            "portfolio_recommendation_id": recommendation.id,
            "market_regime": regime["regime"],
            "lineage": lineage,
            "warnings": warnings,
            "coverage": context.get("coverage", {}),
        }

    @staticmethod
    def _prediction_results(result: dict[str, Any] | list[dict[str, Any]], trade_date: date) -> list[dict[str, Any]]:
        if isinstance(result, list):
            raise QuantDatasetMissingError("Daily Qlib prediction must return a combined result payload")
        if not isinstance(result, dict):
            raise QuantDatasetMissingError("Daily Qlib prediction result is missing")
        if result.get("schema_version") != PROTOCOL_VERSION:
            raise ValueError("Qlib daily prediction result has an unsupported schema_version")
        if result.get("trade_date") not in {None, str(trade_date)}:
            raise ValueError("Qlib daily prediction result trade_date mismatch")
        responses = result.get("results")
        if not isinstance(responses, list) or len(responses) != 2:
            raise QuantDatasetMissingError("Both Qlib prediction results are required")
        return responses

    def _production_model(self, market: str, model_key: str) -> Any:
        model = self.repository.production_model(market, model_key)
        if not model or not model.artifact_uri:
            raise ModelNotPublishedError(f"No production {market} {model_key} model artifact")
        feature_config = getattr(model, "feature_config", None)
        if feature_config is not None and dict(feature_config) != SUPPORTED_QLIB_FEATURE_CONFIG:
            raise ModelNotPublishedError(
                f"Production {market} {model_key} model uses unsupported feature_config={feature_config}; "
                "retrain and publish an Alpha158-only model"
            )
        stored = getattr(model, "target_config", None)
        if not stored_target_matches_production(model_key, stored):
            raise ModelNotPublishedError(
                f"Production {market} {model_key} model uses unsupported target_config={stored}; "
                "retrain and publish with the model-type target semantics"
            )
        return model

    def _preflight_production_models(self, market: str) -> tuple[Any, Any]:
        models = (
            self._production_model(market, CROSS_SECTION_MODEL_KEY),
            self._production_model(market, TIME_SERIES_MODEL_KEY),
        )
        cs_horizon = int((getattr(models[0], "target_config", None) or {}).get("prediction_horizon") or 5)
        ts_horizon = int((getattr(models[1], "target_config", None) or {}).get("prediction_horizon") or 5)
        if cs_horizon != ts_horizon:
            raise ModelNotPublishedError(
                f"Production {market} models must share prediction_horizon; "
                f"cross_section={cs_horizon} time_series={ts_horizon}"
            )
        artifact_store = self.artifact_store or ArtifactStore()
        for model in models:
            artifact_store.resolve_uri(model.artifact_uri)
        return models

    @staticmethod
    def _validate_prediction_coverage(response: dict[str, Any], expected_codes: set[str], trade_date: date) -> None:
        predictions = response.get("predictions")
        model_key = response.get("model_key") or "unknown_model"
        if not isinstance(predictions, list):
            raise PredictionFailedError(
                f"Prediction coverage unavailable for {model_key} on {trade_date}: predictions is not a list"
            )
        codes = [item.get("code") for item in predictions if isinstance(item, dict)]
        invalid_count = len(predictions) - len(codes) + sum(code is None for code in codes)
        valid_codes = [str(code) for code in codes if code is not None]
        counts = Counter(valid_codes)
        duplicates = sorted(code for code, count in counts.items() if count > 1)
        actual_codes = set(valid_codes)
        missing = sorted(expected_codes - actual_codes)
        unexpected = sorted(actual_codes - expected_codes)
        if len(predictions) != len(expected_codes) or missing or unexpected or duplicates or invalid_count:
            raise PredictionFailedError(
                f"Prediction coverage mismatch for {model_key} on {trade_date}: "
                f"expected={len(expected_codes)} actual={len(predictions)} "
                f"missing={missing} unexpected={unexpected} duplicates={duplicates} "
                f"invalid_entries={invalid_count}"
            )

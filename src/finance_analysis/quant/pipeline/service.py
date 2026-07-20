"""Business-side orchestration around JSON-only Qlib task results."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
from finance_analysis.database.repositories.stock_list import StockListRepo
from finance_analysis.database.repositories.user import DEFAULT_ADMIN_EMAIL, UserRepository
from finance_analysis.market_review.trading_calendar import get_effective_trading_date
from finance_analysis.quant.cache import QuantLatestCache, cache_keys
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.exceptions import (
    FeatureDataMissingError,
    ModelNotPublishedError,
    PredictionFailedError,
    QuantDatasetMissingError,
)
from finance_analysis.quant.features.service import DailyResearchService
from finance_analysis.quant.markets import get_quant_market_config, validate_universe_for_market
from finance_analysis.quant.portfolio.builder import PortfolioBuilder
from finance_analysis.quant.signals.fusion import SignalFusion
from finance_analysis.quant.universe.service import DynamicUniverseService
from finance_analysis.stocks.market_scope import MarketDataScopeResolver

PROTOCOL_VERSION = 1


class QuantTrainingPipeline:
    def __init__(self, repository: Any = None):
        self.repository = repository or QuantRepository()

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
            "market": run.market,
            "universe_id": run.universe_id,
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
        run = self._supported_run(run_id)
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
        cache: Any = None,
        exporter: Any = None,
        symbol_repository: Any = None,
        holding_repository: Any = None,
        universe_service: Any = None,
        artifact_store: Any = None,
        owner_uid: int | None = None,
    ):
        self.repository = repository or QuantRepository()
        self.cache = cache or QuantLatestCache()
        self.exporter = exporter or QlibDatasetExporter(self.repository)
        self.symbol_repository = symbol_repository or MarketDataSymbolRepository()
        self.holding_repository = holding_repository or StockListRepo()
        self.universe_service = universe_service
        self.artifact_store = artifact_store
        self.owner_uid = owner_uid

    def prepare(
        self,
        market: str = "US",
        universe_key: str | None = None,
        trade_date: date | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        config = get_quant_market_config(market)
        market = config.market
        if trade_date is None:
            trade_date = get_effective_trading_date(config.calendar_market)
        universe_key = validate_universe_for_market(market, universe_key)
        cross_section, time_series = self._preflight_production_models(market)
        service = self.universe_service or DynamicUniverseService(
            repository=self.repository,
            symbol_repository=self.symbol_repository,
        )
        universe_sync = service.refresh(market, trade_date)
        universe = self.repository.get_universe(universe_key)
        if not universe or universe.market != market or not getattr(universe, "enabled", True):
            raise ValueError(f"Supported {market} universe {universe_key} is not available")
        members = self.repository.active_members(universe.id, trade_date)
        if not members:
            raise FeatureDataMissingError(f"No active universe members for {trade_date}")
        research = DailyResearchService(self.repository).run(market, universe_key, trade_date)
        member_codes = set(research["eligible_codes"])
        available_codes = self.repository.daily_bar_codes(member_codes, trade_date)
        missing_codes = sorted(member_codes - available_codes)
        if missing_codes:
            raise FeatureDataMissingError(
                f"Missing rankable universe daily data for trade_date={trade_date}: {missing_codes}"
            )
        regime = research["market_regime"]
        prediction_dataset = self.exporter.export(
            market,
            universe_key,
            trade_date - timedelta(days=500),
            trade_date,
            candidate_codes=member_codes,
        )
        if prediction_dataset is None or not prediction_dataset.artifact_uri:
            raise QuantDatasetMissingError(
                f"Prediction dataset artifact is unavailable for {trade_date}"
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
            "expected_codes": sorted(member_codes),
            "regime": {
                "id": regime.id,
                "regime": regime.regime,
                "market_score": regime.market_score,
                "max_equity_exposure": regime.max_equity_exposure,
            },
            "warnings": research.get("warnings", []),
            "coverage": research.get("coverage", {}),
            "universe_sync": universe_sync,
        }
        return requests, context

    def finalize(self, responses: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
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
        by_model = {response.get("model_key"): response for response in responses}
        response = by_model.get("cross_section_lgbm")
        time_series_response = by_model.get("time_series_lgbm")
        if response is None or time_series_response is None:
            raise QuantDatasetMissingError("Both Qlib prediction results are required")
        for item in (response, time_series_response):
            if item.get("schema_version") != PROTOCOL_VERSION or item.get("trade_date") != str(trade_date):
                raise ValueError("Qlib prediction result protocol or trade_date mismatch")
        expected_model_runs = {
            "cross_section_lgbm": context["cross_section_model_run_id"],
            "time_series_lgbm": context["time_series_model_run_id"],
        }
        for model_key, item in by_model.items():
            if model_key in expected_model_runs and item.get("model_run_id") not in (None, expected_model_runs[model_key]):
                raise ValueError(f"Qlib prediction result model_run_id mismatch for {model_key}")
        config = get_quant_config()
        feature_context = self.repository.feature_context(
            trade_date, config.feature_version, config.event_feature_version
        )
        member_codes = {symbol.code for _, symbol in self.repository.active_members(universe.id, trade_date)}
        expected_codes = set(context.get("expected_codes") or member_codes)
        if not expected_codes.issubset(member_codes):
            raise ValueError(
                "Daily callback universe membership no longer matches; "
                f"expected={sorted(expected_codes)} active={sorted(member_codes)}"
            )
        self._validate_prediction_coverage(response, expected_codes, trade_date)
        self._validate_prediction_coverage(time_series_response, expected_codes, trade_date)
        time_series_by_code = {
            item["code"]: item["normalized_score"]
            for item in time_series_response["predictions"]
        }
        regime = context["regime"]
        fusion = SignalFusion()
        signal_values: list[dict[str, Any]] = []
        public: list[dict[str, Any]] = []
        for prediction in response.get("predictions", []):
            symbol = self.symbol_repository.get_by_code(prediction["code"])
            if symbol is None:
                raise FeatureDataMissingError(
                    f"Prediction code has no canonical symbol: {prediction['code']}"
                )
            prediction["symbol_id"] = symbol.id
            feature = feature_context.get(symbol.id)
            if feature is None:
                raise FeatureDataMissingError(
                    f"Daily feature context missing for {prediction['code']} on {trade_date}"
                )
            required_metadata = (
                "sector_score",
                "has_sufficient_data",
                "liquidity",
                "risk_penalty",
                "close",
            )
            missing_metadata = [key for key in required_metadata if feature.get(key) is None]
            if missing_metadata:
                raise FeatureDataMissingError(
                    f"Daily feature metadata missing for {prediction['code']} on {trade_date}: "
                    f"{missing_metadata}"
                )
            prediction.update(
                {
                    "time_series_score": time_series_by_code.get(prediction["code"]),
                    "event_score": feature["event_score"],
                    "sector_score": feature["sector_score"],
                    "sector_key": feature.get("sector_key"),
                    "negative_event_veto": feature.get("negative_event_veto", False),
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
        current_weights = self._current_weights(public, market)
        portfolio = PortfolioBuilder().build(
            public,
            regime["max_equity_exposure"],
            current_weights=current_weights,
        )
        self.repository.replace_signals(
            market, universe.id, trade_date, context["cross_section_model_version"], signal_values
        )
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
        warnings: list[str] = [*context.get("warnings", []), *portfolio["warnings"]]
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
            "coverage": context.get("coverage", {}),
        }

    def _production_model(self, market: str, model_key: str) -> Any:
        model = self.repository.production_model(market, model_key)
        if not model or not model.artifact_uri:
            raise ModelNotPublishedError(f"No production {market} {model_key} model artifact")
        return model

    def _preflight_production_models(self, market: str) -> tuple[Any, Any]:
        models = (
            self._production_model(market, "cross_section_lgbm"),
            self._production_model(market, "time_series_lgbm"),
        )
        artifact_store = self.artifact_store or ArtifactStore()
        for model in models:
            artifact_store.resolve_uri(model.artifact_uri)
        return models

    @staticmethod
    def _validate_prediction_coverage(
        response: dict[str, Any], expected_codes: set[str], trade_date: date
    ) -> None:
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
        if (
            len(predictions) != len(expected_codes)
            or missing
            or unexpected
            or duplicates
            or invalid_count
        ):
            raise PredictionFailedError(
                f"Prediction coverage mismatch for {model_key} on {trade_date}: "
                f"expected={len(expected_codes)} actual={len(predictions)} "
                f"missing={missing} unexpected={unexpected} duplicates={duplicates} "
                f"invalid_entries={invalid_count}"
            )

    def _current_weights(self, signals: list[dict[str, Any]], market: str) -> dict[str, float]:
        if self.owner_uid is None:
            owner = UserRepository().get_by_email(DEFAULT_ADMIN_EMAIL)
            if owner is None:
                raise FeatureDataMissingError(
                    "Cannot load quant holdings because the default admin user is unavailable"
                )
            owner_uid = owner.id
        else:
            owner_uid = self.owner_uid
        holdings = self.holding_repository.list_all(uid=owner_uid)
        member_codes = {item["code"] for item in signals}
        closes = {item["code"]: float(item["close"]) for item in signals}
        market_values: dict[str, float] = {}
        for holding in holdings:
            quantity = float(holding.quantity or 0)
            if quantity <= 0:
                continue
            raw_code = str(holding.code or "").strip().upper()
            candidates = [raw_code]
            if market == "US" and not raw_code.endswith(".US"):
                candidates.append(f"{raw_code}.US")
            elif market == "CN":
                try:
                    candidates.append(MarketDataScopeResolver.canonical_code(raw_code, "CN"))
                except ValueError:
                    pass
            code = next((candidate for candidate in candidates if candidate in member_codes), None)
            if code is None:
                continue
            close = closes.get(code)
            if close is None or close <= 0:
                raise FeatureDataMissingError(
                    f"Cannot value current holding {code}: daily close is unavailable"
                )
            market_values[code] = market_values.get(code, 0.0) + quantity * close
        total_value = sum(market_values.values())
        if total_value <= 0:
            return {}
        return {code: value / total_value for code, value in market_values.items()}

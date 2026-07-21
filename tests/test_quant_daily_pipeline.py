from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.config import DataProviderConfig
from finance_analysis.quant.exceptions import (
    FeatureDataMissingError,
    ModelArtifactMissingError,
    ModelNotPublishedError,
    PortfolioConstraintError,
    PredictionFailedError,
)
from finance_analysis.quant.features.service import DailyResearchService
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.pipeline.service import PROTOCOL_VERSION, QuantDailyPipeline, QuantTrainingPipeline
from finance_analysis.quant.portfolio.builder import PortfolioBuilder

TRADE_DATE = date(2026, 7, 16)


def _member(code: str, symbol_id: int):
    return (
        SimpleNamespace(sector_key="semiconductor", sector_benchmark_code="SOXX.US"),
        SimpleNamespace(id=symbol_id, code=code),
    )


def test_prepare_rejects_universe_member_without_target_daily_bar(monkeypatch) -> None:
    repository = MagicMock()
    repository.get_universe.return_value = SimpleNamespace(
        id=3, key="us_sp500", market="US", enabled=True
    )
    repository.active_members.return_value = [
        _member("AAPL.US", 1),
        _member("NVDA.US", 2),
    ]
    repository.daily_bar_codes.return_value = {"AAPL.US"}
    pipeline = QuantDailyPipeline(
        repository=repository,
        cache=MagicMock(),
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        holding_repository=MagicMock(),
        universe_service=MagicMock(),
        artifact_store=MagicMock(),
        owner_uid=7,
    )
    repository.production_model.side_effect = [
        SimpleNamespace(artifact_uri="quant://us/cs"),
        SimpleNamespace(artifact_uri="quant://us/ts"),
    ]
    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.DailyResearchService",
        lambda _repository: SimpleNamespace(
            run=lambda *_args: {
                "eligible_codes": ["AAPL.US", "NVDA.US"],
                "market_regime": SimpleNamespace(
                    id=1, regime="neutral", market_score=0.5, max_equity_exposure=0.4
                ),
            }
        ),
    )

    with pytest.raises(FeatureDataMissingError, match=r"2026-07-16.*NVDA\.US"):
        pipeline.prepare(market="US", trade_date=TRADE_DATE)

    repository.production_model.assert_any_call("US", "cross_section_lgbm")


@pytest.mark.parametrize(
    ("production_models", "missing_model"),
    [
        ([None], "cross_section_lgbm"),
        ([SimpleNamespace(artifact_uri="quant://us/cs"), None], "time_series_lgbm"),
    ],
)
def test_prepare_rejects_missing_model_before_universe_refresh(
    production_models: list[object], missing_model: str
) -> None:
    repository = MagicMock()
    repository.production_model.side_effect = production_models
    universe_service = MagicMock()
    artifact_store = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        cache=MagicMock(),
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        holding_repository=MagicMock(),
        universe_service=universe_service,
        artifact_store=artifact_store,
        owner_uid=7,
    )

    with pytest.raises(ModelNotPublishedError, match=rf"US {missing_model}"):
        pipeline.prepare(market="US", trade_date=TRADE_DATE)

    universe_service.refresh.assert_not_called()
    repository.get_universe.assert_not_called()
    artifact_store.resolve_uri.assert_not_called()


def test_prepare_rejects_missing_model_artifact_before_universe_refresh() -> None:
    repository = MagicMock()
    repository.production_model.side_effect = [
        SimpleNamespace(artifact_uri="quant://us/cs"),
        SimpleNamespace(artifact_uri="quant://us/ts"),
    ]
    artifact_store = MagicMock()
    artifact_store.resolve_uri.side_effect = ModelArtifactMissingError(
        "Artifact does not exist: quant://us/cs"
    )
    universe_service = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        cache=MagicMock(),
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        holding_repository=MagicMock(),
        universe_service=universe_service,
        artifact_store=artifact_store,
        owner_uid=7,
    )

    with pytest.raises(ModelArtifactMissingError, match="quant://us/cs"):
        pipeline.prepare(market="US", trade_date=TRADE_DATE)

    universe_service.refresh.assert_not_called()
    repository.get_universe.assert_not_called()


def test_prepare_rejects_unsupported_universe_before_refresh() -> None:
    universe_service = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=MagicMock(),
        cache=MagicMock(),
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        holding_repository=MagicMock(),
        universe_service=universe_service,
        owner_uid=7,
    )

    with pytest.raises(ValueError, match=r"only supported universe is us_sp500"):
        pipeline.prepare(universe_key="us_ai_semiconductor", trade_date=TRADE_DATE)

    universe_service.refresh.assert_not_called()


def test_prediction_coverage_lists_missing_symbols() -> None:
    response = {
        "model_key": "cross_section_lgbm",
        "predictions": [{"code": "AAPL.US", "normalized_score": 0.8}],
    }

    with pytest.raises(PredictionFailedError) as exc_info:
        QuantDailyPipeline._validate_prediction_coverage(response, {"AAPL.US", "NVDA.US"}, TRADE_DATE)

    message = str(exc_info.value)
    assert "expected=2 actual=1" in message
    assert "missing=['NVDA.US']" in message


def test_finalize_passes_valued_real_holdings_to_portfolio_builder(monkeypatch) -> None:
    members = [_member("AAPL.US", 1), _member("NVDA.US", 2)]

    class Repository:
        def __init__(self):
            self.replaced = None

        def get_universe(self, key):
            return SimpleNamespace(
                id=3, key="us_sp500", market="US", enabled=True
            )

        def active_members(self, universe_id, trade_date):
            return members

        def feature_context(self, trade_date, feature_version, event_feature_version):
            common = {
                "event_score": 0.2,
                "sector_score": 0.7,
                "sector_key": "semiconductor",
                "negative_event_veto": False,
                "has_sufficient_data": True,
                "liquidity": 2_000_000,
                "risk_penalty": 0.04,
            }
            return {
                1: {**common, "close": 100.0},
                2: {**common, "close": 200.0},
            }

        def replace_signals(self, market, universe_id, trade_date, model_version, values):
            self.replaced = values

        def save_portfolio(self, values, items):
            return SimpleNamespace(id=99)

    class Symbols:
        @staticmethod
        def get_by_code(code):
            return {"AAPL.US": members[0][1], "NVDA.US": members[1][1]}.get(code)

    holdings = MagicMock()
    holdings.list_all.return_value = [
        SimpleNamespace(code="AAPL", quantity=10),
        SimpleNamespace(code="NVDA.US", quantity=5),
    ]
    captured = {}

    class CapturingPortfolioBuilder:
        def build(self, signals, max_equity_exposure, current_weights=None):
            captured["signals"] = signals
            captured["current_weights"] = current_weights
            return {
                "items": [],
                "target_equity_exposure": 0,
                "sector_exposure": {},
                "warnings": [],
                "config": {},
            }

    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.PortfolioBuilder",
        CapturingPortfolioBuilder,
    )
    repository = Repository()
    cache = MagicMock()
    cache.set.return_value = True
    pipeline = QuantDailyPipeline(
        repository=repository,
        cache=cache,
        exporter=MagicMock(),
        symbol_repository=Symbols(),
        holding_repository=holdings,
        owner_uid=7,
    )
    context = {
        "schema_version": PROTOCOL_VERSION,
        "trade_date": str(TRADE_DATE),
        "market": "US",
        "universe_key": "us_sp500",
        "universe_id": 3,
        "cross_section_model_version": "v1",
        "cross_section_model_run_id": 11,
        "time_series_model_run_id": 12,
        "expected_codes": ["AAPL.US", "NVDA.US"],
        "regime": {
            "id": 8,
            "regime": "risk_on",
            "market_score": 0.8,
            "max_equity_exposure": 0.8,
        },
    }
    responses = [
        {
            "schema_version": PROTOCOL_VERSION,
            "trade_date": str(TRADE_DATE),
            "model_key": "cross_section_lgbm",
            "predictions": [
                {"code": "AAPL.US", "normalized_score": 0.8},
                {"code": "NVDA.US", "normalized_score": 0.7},
            ],
        },
        {
            "schema_version": PROTOCOL_VERSION,
            "trade_date": str(TRADE_DATE),
            "model_key": "time_series_lgbm",
            "predictions": [
                {"code": "AAPL.US", "normalized_score": 0.6},
                {"code": "NVDA.US", "normalized_score": 0.5},
            ],
        },
    ]

    result = pipeline.finalize(responses, context)

    assert result["signal_count"] == 2
    assert captured["current_weights"] == pytest.approx({"AAPL.US": 0.5, "NVDA.US": 0.5})
    assert all(item["risk_penalty"] == 0.04 for item in captured["signals"])
    holdings.list_all.assert_called_once_with(uid=7)


def test_finalize_rejects_unsupported_callback_context_before_writes() -> None:
    repository = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        cache=MagicMock(),
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        holding_repository=MagicMock(),
        owner_uid=7,
    )
    context = {
        "schema_version": PROTOCOL_VERSION,
        "trade_date": str(TRADE_DATE),
        "market": "US",
        "universe_key": "us_ai_semiconductor",
        "universe_id": 3,
    }

    with pytest.raises(ValueError, match="only supported universe"):
        pipeline.finalize([], context)

    repository.replace_signals.assert_not_called()
    repository.save_portfolio.assert_not_called()


def test_training_and_dataset_export_reject_unsupported_universe() -> None:
    repository = MagicMock()
    repository.get_model_run.return_value = SimpleNamespace(
        id=5,
        market="US",
        universe_id=9,
        dataset_snapshot_id=4,
    )
    repository.get_universe.return_value = SimpleNamespace(
        id=9,
        key="us_ai_semiconductor",
        market="US",
        enabled=False,
    )

    with pytest.raises(ValueError, match=r"only supported universe is us_sp500"):
        QuantTrainingPipeline(repository).prepare(5)
    with pytest.raises(ValueError, match=r"only supported universe is us_sp500"):
        QlibDatasetExporter(repository=repository, artifact_store=MagicMock()).export(
            "US",
            "us_ai_semiconductor",
            date(2025, 1, 1),
            date(2025, 12, 31),
        )

    repository.create_dataset.assert_not_called()
    repository.update_model_run.assert_not_called()


def test_training_rejects_missing_dataset_artifact_before_marking_training() -> None:
    repository = MagicMock()
    repository.get_model_run.return_value = SimpleNamespace(
        id=5,
        market="CN",
        universe_id=9,
        dataset_snapshot_id=4,
    )
    repository.get_universe.return_value = SimpleNamespace(
        id=9,
        key="cn_csi300",
        market="CN",
        enabled=True,
    )
    repository.get_dataset.return_value = SimpleNamespace(
        id=4,
        market="CN",
        universe_id=9,
        status="ready",
        artifact_uri="quant://datasets/missing",
        price_mode="forward_adjusted",
    )
    artifact_store = MagicMock()
    artifact_store.resolve_uri.side_effect = ModelArtifactMissingError(
        "Artifact does not exist: quant://datasets/missing"
    )

    with pytest.raises(ModelArtifactMissingError, match="quant://datasets/missing"):
        QuantTrainingPipeline(repository, artifact_store=artifact_store).prepare(5)

    repository.update_model_run.assert_not_called()


def test_portfolio_metadata_uses_twenty_day_turnover_and_realized_risk() -> None:
    dates = pd.bdate_range(end=TRADE_DATE, periods=61)
    bars = pd.DataFrame(
        {
            "date": dates.date,
            "close": 100.0,
            "volume": 20_000.0,
            "amount": None,
        }
    )
    features = pd.Series(
        {
            "ret_60d": 0.1,
            "price_ma60_ratio": 0.05,
            "realized_vol_20d": 0.4,
            "relative_20d_to_market": 0.02,
            "relative_20d_to_sector": 0.01,
        }
    )

    metadata = DailyResearchService._portfolio_metadata(bars, features, TRADE_DATE)

    assert metadata["has_sufficient_data"] is True
    assert metadata["liquidity"] == pytest.approx(2_000_000)
    assert metadata["risk_penalty"] == pytest.approx(0.04)


def test_portfolio_filters_low_liquidity_without_default_pass_through() -> None:
    signals = [
        {
            "code": "LIQUID.US",
            "symbol_id": 1,
            "final_score": 0.9,
            "sector_key": "one",
            "signal": "buy",
            "reasons": [],
            "vetoed": False,
            "has_sufficient_data": True,
            "liquidity": 2_000_000,
        },
        {
            "code": "THIN.US",
            "symbol_id": 2,
            "final_score": 0.8,
            "sector_key": "two",
            "signal": "buy",
            "reasons": [],
            "vetoed": False,
            "has_sufficient_data": True,
            "liquidity": 100_000,
        },
    ]

    result = PortfolioBuilder().build(signals, 0.8)

    assert [item["code"] for item in result["items"]] == ["LIQUID.US"]
    assert "THIN.US" in result["warnings"][0]
    with pytest.raises(PortfolioConstraintError, match="Portfolio metadata is missing"):
        PortfolioBuilder().build([{**signals[0], "liquidity": None}], 0.8)


def test_portfolio_uses_current_weights_for_actions_and_daily_limits() -> None:
    signals = [
        {
            "code": f"S{i}.US",
            "symbol_id": i,
            "final_score": 1 - i * 0.02,
            "sector_key": f"sector-{i}",
            "signal": "buy",
            "reasons": [],
            "vetoed": False,
            "has_sufficient_data": True,
            "liquidity": 2_000_000,
        }
        for i in range(22)
    ]
    current_weights = {"S1.US": 0.08, "S2.US": 0.10, "S21.US": 0.05}

    result = PortfolioBuilder().build(signals, 0.8, current_weights=current_weights)
    actions = {item["code"]: item["action"] for item in result["items"]}

    assert actions["S0.US"] == "buy"
    assert actions["S1.US"] == "hold"
    assert actions["S2.US"] == "reduce"
    assert actions["S21.US"] == "sell"
    assert sum(max(0, item["weight_change"]) for item in result["items"]) <= 0.20 + 1e-9
    assert sum(abs(item["weight_change"]) for item in result["items"]) <= 0.30 + 1e-9


def test_scheduled_daily_history_defaults_use_recent_postgres_windows() -> None:
    config = DataProviderConfig()
    assert config.market_data_initial_daily_days == 5 * 365
    assert config.market_data_refresh_daily_days == 60
    assert config.market_data_retention_daily_days == 5 * 365

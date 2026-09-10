from __future__ import annotations

from dataclasses import replace
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
    QuantDatasetMissingError,
)
from finance_analysis.quant.features.service import DailyResearchService
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.markets import get_universe_codes
from finance_analysis.quant.pipeline.service import PROTOCOL_VERSION, QuantDailyPipeline, QuantTrainingPipeline
from finance_analysis.quant.portfolio.builder import PortfolioBuilder

TRADE_DATE = date(2026, 7, 16)


def _published(model_key: str, *, market: str = "US", **overrides):
    cross_section = model_key == "cross_section_lgbm"
    values = {
        "id": 11 if cross_section else 12,
        "model_key": model_key,
        "model_version": f"{market.lower()}-v1",
        "artifact_uri": f"quant://{market.lower()}/{'cs' if cross_section else 'ts'}",
        "feature_config": {"base": "Alpha158"},
        "target_config": {
            "prediction_horizon": 5,
            "entry_price": "open",
            "exit_price": "close",
            "benchmark": "market" if cross_section else "none",
            "excess_return": cross_section,
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)



@pytest.fixture(autouse=True)
def _db_universe(monkeypatch):
    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.get_universe_codes",
        lambda market: {"600519.SH"} if str(market).upper() == "CN" else {"AAPL.US", "NVDA.US"},
    )


def _instrument(code: str, instrument_id: int):
    return SimpleNamespace(id=instrument_id, code=code)


def test_daily_research_uses_csi300_primary_and_growth_style_benchmarks(
    monkeypatch,
) -> None:
    dates = pd.bdate_range(end=TRADE_DATE, periods=90)

    def bars(code: str, drift: float) -> pd.DataFrame:
        close = pd.Series([100.0 + index * drift for index in range(len(dates))])
        return pd.DataFrame(
            {
                "instrument": code,
                "datetime": dates.date,
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000.0,
                "amount": close * 1_000.0,
            }
        )

    loaded = SimpleNamespace(
        frame=pd.concat(
            [
                bars("600519.SH", 0.8),
                bars("159915.SZ", 1.0),
                bars("510300.SH", 0.5),
            ],
            ignore_index=True,
        ),
        vwap={"valid_rows": len(dates) * 3},
    )
    repository = MagicMock()
    repository.get_universe.return_value = SimpleNamespace(id=1, key="cn_quant", market="CN", enabled=True)
    repository.save_market_regime.return_value = SimpleNamespace(id=7, regime="neutral")
    symbol_repository = MagicMock()
    symbol_repository.list_enabled_daily_by_codes.return_value = [SimpleNamespace(id=1, code="600519.SH")]
    captured = {}

    class MarketRegimeServiceStub:
        def __init__(self, _config):
            pass

        def calculate(
            self,
            primary,
            broad,
            universe,
            *,
            benchmark_labels,
            style,
            style_label,
        ):
            captured.update(
                primary=primary,
                broad=broad,
                universe=universe,
                benchmark_labels=benchmark_labels,
                style=style,
                style_label=style_label,
            )
            return SimpleNamespace(
                regime="neutral",
                market_score=0.5,
                max_equity_exposure=0.4,
                features={},
                reasons=[],
            )

    monkeypatch.setattr(
        "finance_analysis.quant.features.service.get_universe_codes",
        lambda _market: {"600519.SH", "000001.SZ"},
    )
    monkeypatch.setattr(
        "finance_analysis.quant.features.service.DailyBarLoader",
        lambda _repository: SimpleNamespace(load=lambda *_args: loaded),
    )
    monkeypatch.setattr(
        "finance_analysis.quant.features.service.MarketRegimeService",
        MarketRegimeServiceStub,
    )

    market_data = MagicMock()
    market_data.get_daily_bars.return_value = SimpleNamespace(
        data={
            code: [
                SimpleNamespace(
                    trade_date=row.datetime,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    amount=row.amount,
                )
                for row in loaded.frame[loaded.frame.instrument == code].itertuples()
            ]
            for code in ("159915.SZ", "510300.SH")
        }
    )
    service = DailyResearchService(repository, symbol_repository, market_data=market_data)
    with pytest.raises(FeatureDataMissingError, match="coverage below minimum"):
        service.run("CN", "cn_quant", TRADE_DATE)
    repository.save_market_regime.assert_not_called()

    service.config = replace(service.config, minimum_universe_coverage=0.5)
    result = service.run("CN", "cn_quant", TRADE_DATE)
    assert set(market_data.get_daily_bars.call_args.args[0]) == {"159915.SZ", "510300.SH"}
    assert market_data.get_daily_bars.call_args.kwargs["source_policy"] == "db_fresh"

    assert captured["benchmark_labels"] == ("510300.SH", "510300.SH")
    assert captured["style_label"] == "159915.SZ"
    assert captured["primary"]["close"].iloc[-1] == captured["broad"]["close"].iloc[-1]
    assert captured["style"]["close"].iloc[-1] != captured["primary"]["close"].iloc[-1]
    assert set(captured["universe"]) == {"600519.SH"}
    assert result["context_count"] == 1
    assert set(result["runtime_context"]) == {"600519.SH"}
    assert result["coverage"]["coverage_ratio"] == pytest.approx(0.5)
    assert result["coverage"]["skipped_codes"] == ["000001.SZ"]
    assert "行情覆盖 1/2" in result["warnings"][0]


def test_prepare_rejects_research_symbol_without_target_daily_bar(monkeypatch) -> None:
    repository = MagicMock()
    repository.get_universe.return_value = SimpleNamespace(id=3, key="us_quant", market="US", enabled=True)
    repository.daily_bar_codes.return_value = {"AAPL.US"}
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        artifact_store=MagicMock(),
    )
    repository.production_model.side_effect = [
        _published("cross_section_lgbm"),
        _published("time_series_lgbm"),
    ]
    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.DailyResearchService",
        lambda _repository, **_kwargs: SimpleNamespace(
            run=lambda *_args: {
                "eligible_codes": ["AAPL.US", "NVDA.US"],
                "runtime_context": {},
                "market_regime": SimpleNamespace(id=1, regime="neutral", market_score=0.5, max_equity_exposure=0.4),
            }
        ),
    )

    with pytest.raises(FeatureDataMissingError, match=r"2026-07-16.*NVDA\.US"):
        pipeline.prepare(market="US", trade_date=TRADE_DATE)

    repository.production_model.assert_any_call("US", "cross_section_lgbm")


def test_prepare_does_not_require_universe_member_repository_methods(monkeypatch) -> None:
    repository = MagicMock(spec_set=["production_model", "get_universe", "daily_bar_codes"])
    repository.production_model.side_effect = [
        _published("cross_section_lgbm", model_version="v1"),
        _published("time_series_lgbm", model_version="v1"),
    ]
    repository.get_universe.return_value = SimpleNamespace(id=3, key="us_quant", market="US", enabled=True)
    repository.daily_bar_codes.return_value = {"AAPL.US"}
    exporter = MagicMock()
    exporter.export.return_value = SimpleNamespace(artifact_uri="quant://us/dataset")
    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.DailyResearchService",
        lambda _repository, **_kwargs: SimpleNamespace(
            run=lambda *_args: {
                "eligible_codes": ["AAPL.US"],
                "runtime_context": {
                    "AAPL.US": {
                        "has_sufficient_data": True,
                        "liquidity": 2_000_000,
                        "risk_penalty": 0.04,
                        "close": 100,
                    }
                },
                "market_regime": SimpleNamespace(
                    id=1,
                    regime="neutral",
                    market_score=0.5,
                    max_equity_exposure=0.4,
                ),
            }
        ),
    )

    payload, context = QuantDailyPipeline(
        repository=repository,
        exporter=exporter,
        symbol_repository=MagicMock(),
        artifact_store=MagicMock(),
    ).prepare(market="US", trade_date=TRADE_DATE)

    assert payload["schema_version"] == PROTOCOL_VERSION
    assert payload["cross_section"]["model_key"] == "cross_section_lgbm"
    assert payload["time_series"]["model_key"] == "time_series_lgbm"
    assert payload["dataset_uri"] == "quant://us/dataset"
    assert context["expected_codes"] == ["AAPL.US"]
    assert context["lineage"]["cross_section_model_run_id"] == 11
    assert context["lineage"]["time_series_model_run_id"] == 12


@pytest.mark.parametrize(
    ("production_models", "missing_model"),
    [
        ([None], "cross_section_lgbm"),
        ([SimpleNamespace(artifact_uri="quant://us/cs"), None], "time_series_lgbm"),
    ],
)
def test_prepare_rejects_missing_model_before_universe_lookup(
    production_models: list[object], missing_model: str
) -> None:
    repository = MagicMock()
    repository.production_model.side_effect = production_models
    artifact_store = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        artifact_store=artifact_store,
    )

    with pytest.raises(ModelNotPublishedError, match=rf"US {missing_model}"):
        pipeline.prepare(market="US", trade_date=TRADE_DATE)

    repository.get_universe.assert_not_called()
    artifact_store.resolve_uri.assert_not_called()


def test_prepare_rejects_missing_model_artifact_before_universe_lookup() -> None:
    repository = MagicMock()
    repository.production_model.side_effect = [
        _published("cross_section_lgbm"),
        _published("time_series_lgbm"),
    ]
    artifact_store = MagicMock()
    artifact_store.resolve_uri.side_effect = ModelArtifactMissingError("Artifact does not exist: quant://us/cs")
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        artifact_store=artifact_store,
    )

    with pytest.raises(ModelArtifactMissingError, match="quant://us/cs"):
        pipeline.prepare(market="US", trade_date=TRADE_DATE)

    repository.get_universe.assert_not_called()


def test_prepare_rejects_legacy_production_model_before_universe_lookup() -> None:
    repository = MagicMock()
    repository.production_model.return_value = SimpleNamespace(
        artifact_uri="quant://cn/legacy",
        feature_config={"base": "Alpha158", "ablation": "all_features"},
    )
    artifact_store = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        artifact_store=artifact_store,
    )

    with pytest.raises(ModelNotPublishedError, match="retrain and publish an Alpha158-only model"):
        pipeline.prepare(market="CN", trade_date=TRADE_DATE)

    repository.get_universe.assert_not_called()
    artifact_store.resolve_uri.assert_not_called()


def test_prepare_rejects_unsupported_universe_before_lookup() -> None:
    pipeline = QuantDailyPipeline(
        repository=MagicMock(),
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
    )

    with pytest.raises(ValueError, match=r"only supported universe is us_quant"):
        pipeline.prepare(universe_key="us_ai_semiconductor", trade_date=TRADE_DATE)


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


def test_finalize_builds_recommendation_without_personal_holdings(monkeypatch) -> None:
    instruments = [_instrument("AAPL.US", 1), _instrument("NVDA.US", 2)]

    class Repository:
        def __init__(self):
            self.replaced = None
            self.portfolio_values = None

        def get_universe(self, key):
            return SimpleNamespace(id=3, key="us_quant", market="US", enabled=True)

        def replace_signals_and_save_portfolio(
            self, market, universe_id, trade_date, model_version, signals, portfolio_values, portfolio_items
        ):
            self.replaced = signals
            self.portfolio_values = portfolio_values
            return SimpleNamespace(id=99)

    class Symbols:
        @staticmethod
        def get_by_code(code):
            return {"AAPL.US": instruments[0], "NVDA.US": instruments[1]}.get(code)

    captured = {}

    class CapturingPortfolioBuilder:
        def build(self, signals, max_equity_exposure):
            captured["signals"] = signals
            return {
                "items": [],
                "target_equity_exposure": 0,
                "warnings": [],
                "config": {},
            }

    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.PortfolioBuilder",
        CapturingPortfolioBuilder,
    )
    repository = Repository()
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=Symbols(),
    )
    context = {
        "schema_version": PROTOCOL_VERSION,
        "trade_date": str(TRADE_DATE),
        "market": "US",
        "universe_key": "us_quant",
        "universe_id": 3,
        "cross_section_model_version": "v1",
        "cross_section_model_run_id": 11,
        "time_series_model_run_id": 12,
        "expected_codes": ["AAPL.US", "NVDA.US"],
        "runtime_context": {
            "AAPL.US": {
                "has_sufficient_data": True,
                "liquidity": 2_000_000,
                "risk_penalty": 0.04,
                "close": 100.0,
            },
            "NVDA.US": {
                "has_sufficient_data": True,
                "liquidity": 2_000_000,
                "risk_penalty": 0.04,
                "close": 200.0,
            },
        },
        "warnings": ["行情覆盖 2/3；已跳过缺失数据标的"],
        "coverage": {"universe_members": 3, "rankable_members": 2, "skipped_members": 1},
        "lineage": {
            "cross_section_model_run_id": 11,
            "cross_section_model_version": "v1",
            "time_series_model_run_id": 12,
            "time_series_model_version": "v1",
            "fusion_version": "fusion-rules-v3",
            "portfolio_version": "portfolio-rules-v3",
        },
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

    result = pipeline.finalize(
        {"schema_version": PROTOCOL_VERSION, "trade_date": str(TRADE_DATE), "results": responses},
        context,
    )

    assert result["signal_count"] == 2
    assert all(item["risk_penalty"] == 0.04 for item in captured["signals"])
    assert repository.portfolio_values["warnings"] == ["行情覆盖 2/3；已跳过缺失数据标的"]
    assert repository.portfolio_values["summary"]["coverage"]["skipped_members"] == 1
    assert captured["signals"][0]["score_components"]["lineage"]["cross_section_model_run_id"] == 11
    assert captured["signals"][0]["score_components"]["lineage"]["time_series_model_run_id"] == 12
    assert captured["signals"][0]["score_components"]["lineage"] == repository.portfolio_values["summary"]["lineage"]
    assert "regime_multiplier" not in captured["signals"][0]["score_components"]
    assert result["lineage"]["fusion_version"] == "fusion-rules-v3"


def test_finalize_rejects_unsupported_callback_context_before_writes() -> None:
    repository = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
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
    repository.replace_signals_and_save_portfolio.assert_not_called()


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

    with pytest.raises(ValueError, match=r"only supported universe is us_quant"):
        QuantTrainingPipeline(repository).prepare(5)
    with pytest.raises(ValueError, match=r"only supported universe is us_quant"):
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
        key="cn_quant",
        market="CN",
        enabled=True,
    )
    repository.get_dataset.return_value = SimpleNamespace(
        id=4,
        market="CN",
        universe_id=9,
        status="ready",
        artifact_uri="quant://datasets/missing",
        symbol_count=1,
    )
    artifact_store = MagicMock()
    artifact_store.resolve_uri.side_effect = ModelArtifactMissingError(
        "Artifact does not exist: quant://datasets/missing"
    )

    with pytest.raises(ModelArtifactMissingError, match="quant://datasets/missing"):
        QuantTrainingPipeline(repository, artifact_store=artifact_store).prepare(5)

    repository.update_model_run.assert_not_called()


def test_portfolio_context_uses_twenty_day_turnover_and_realized_risk() -> None:
    dates = pd.bdate_range(end=TRADE_DATE, periods=61)
    bars = pd.DataFrame(
        {
            "date": dates.date,
            "close": 100.0,
            "volume": 20_000.0,
            "amount": None,
        }
    )
    bars["close"] = [100 + index * 0.4 for index in range(len(bars))]
    metadata = DailyResearchService._portfolio_metadata(bars, TRADE_DATE)

    assert metadata["has_sufficient_data"] is True
    assert metadata["liquidity"] > 2_000_000
    assert 0 <= metadata["risk_penalty"] <= 0.15


def test_portfolio_filters_low_liquidity_without_default_pass_through() -> None:
    signals = [
        {
            "code": "LIQUID.US",
            "instrument_id": 1,
            "final_score": 0.9,
            "signal": "buy",
            "reasons": [],
            "has_sufficient_data": True,
            "liquidity": 2_000_000,
        },
        {
            "code": "THIN.US",
            "instrument_id": 2,
            "final_score": 0.8,
            "signal": "buy",
            "reasons": [],
            "has_sufficient_data": True,
            "liquidity": 100_000,
        },
    ]

    result = PortfolioBuilder().build(signals, 0.8)

    assert [item["code"] for item in result["items"]] == ["LIQUID.US"]
    assert any("THIN.US" in warning for warning in result["warnings"])
    with pytest.raises(PortfolioConstraintError, match="Portfolio metadata is missing"):
        PortfolioBuilder().build([{**signals[0], "liquidity": None}], 0.8)


def test_portfolio_excludes_non_buy_signals() -> None:
    signals = [
        {
            "code": f"S{i}.SZ",
            "instrument_id": i,
            "final_score": 0.3 - i * 0.01,
            "signal": "avoid",
            "reasons": [],
            "has_sufficient_data": True,
            "liquidity": 2_000_000,
        }
        for i in range(8)
    ]

    result = PortfolioBuilder().build(signals, 0.1)

    assert result["items"] == []
    assert result["target_equity_exposure"] == 0
    assert "没有满足入选阈值" in result["warnings"][0]


def test_portfolio_contains_only_ranked_model_target_weights() -> None:
    signals = [
        {
            "code": f"S{i}.US",
            "instrument_id": i,
            "final_score": 1 - i * 0.02,
            "signal": "buy",
            "reasons": [],
            "has_sufficient_data": True,
            "liquidity": 2_000_000,
        }
        for i in range(22)
    ]
    result = PortfolioBuilder().build(signals, 0.8)

    assert [item["code"] for item in result["items"]] == [f"S{i}.US" for i in range(10)]
    assert all(item["target_weight"] == pytest.approx(0.08) for item in result["items"])
    assert result["target_equity_exposure"] == pytest.approx(0.80)
    assert all(
        not {"action", "current_weight", "weight_change", "previous_rank", "sector_key"} & item.keys()
        for item in result["items"]
    )


def test_scheduled_daily_history_defaults_use_recent_postgres_windows() -> None:
    config = DataProviderConfig()
    assert config.market_data_initial_daily_days == 5 * 365
    assert config.market_data_refresh_daily_days == 60
    assert config.market_data_retention_daily_days == 5 * 365


def test_finalize_rejects_partial_prediction_payload() -> None:
    repository = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
    )
    context = {
        "schema_version": PROTOCOL_VERSION,
        "trade_date": str(TRADE_DATE),
        "market": "US",
        "universe_key": "us_quant",
        "universe_id": 3,
        "cross_section_model_run_id": 11,
        "time_series_model_run_id": 12,
    }
    repository.get_universe.return_value = SimpleNamespace(id=3, key="us_quant", market="US", enabled=True)

    with pytest.raises(QuantDatasetMissingError, match="combined result payload"):
        pipeline.finalize(
            [
                {
                    "schema_version": PROTOCOL_VERSION,
                    "trade_date": str(TRADE_DATE),
                    "model_key": "cross_section_lgbm",
                    "predictions": [],
                }
            ],
            context,
        )
    with pytest.raises(QuantDatasetMissingError, match="Both Qlib prediction results"):
        pipeline.finalize(
            {
                "schema_version": PROTOCOL_VERSION,
                "trade_date": str(TRADE_DATE),
                "results": [
                    {
                        "schema_version": PROTOCOL_VERSION,
                        "trade_date": str(TRADE_DATE),
                        "model_key": "cross_section_lgbm",
                        "predictions": [],
                    }
                ],
            },
            context,
        )

    repository.replace_signals_and_save_portfolio.assert_not_called()


def test_prepare_rejects_legacy_time_series_excess_return_target() -> None:
    repository = MagicMock()
    repository.production_model.side_effect = [
        _published("cross_section_lgbm"),
        _published(
            "time_series_lgbm",
            target_config={
                "prediction_horizon": 5,
                "entry_price": "open",
                "exit_price": "close",
                "benchmark": "market",
                "excess_return": True,
            },
        ),
    ]
    artifact_store = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        artifact_store=artifact_store,
    )

    with pytest.raises(ModelNotPublishedError, match="5-session target contract"):
        pipeline.prepare(market="US", trade_date=TRADE_DATE)

    repository.get_universe.assert_not_called()
    artifact_store.resolve_uri.assert_not_called()


def test_prepare_rejects_non_five_session_production_horizon() -> None:
    repository = MagicMock()
    repository.production_model.side_effect = [
        _published(
            "cross_section_lgbm",
            target_config={
                "prediction_horizon": 10,
                "entry_price": "open",
                "exit_price": "close",
                "benchmark": "market",
                "excess_return": True,
            },
        ),
        _published("time_series_lgbm"),
    ]
    artifact_store = MagicMock()
    pipeline = QuantDailyPipeline(
        repository=repository,
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        artifact_store=artifact_store,
    )

    with pytest.raises(ModelNotPublishedError, match="5-session target contract"):
        pipeline.prepare(market="US", trade_date=TRADE_DATE)

    repository.get_universe.assert_not_called()
    artifact_store.resolve_uri.assert_not_called()

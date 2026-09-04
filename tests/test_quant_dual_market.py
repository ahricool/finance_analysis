from __future__ import annotations

import os
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from celery.canvas import _chord
from celery.utils.functional import arity_greater

from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.seed import seed_quant_reference_data
from finance_analysis.database.session import DatabaseManager
from finance_analysis.quant.exceptions import ModelNotPublishedError
from finance_analysis.quant.markets import (
    DEFAULT_QUANT_UNIVERSES,
    default_universe_for_market,
    get_universe_codes,
    get_quant_market_config,
    validate_universe_for_market,
)
from finance_analysis.quant.pipeline.service import QuantDailyPipeline
from finance_analysis.quant.sectors.service import build_synthetic_sector_benchmark
from finance_analysis.stocks.market_scope import MarketDataScopeResolver
from finance_analysis.tasks.celery.jobs.quant_daily import tasks as quant_daily_tasks

TRADE_DATE = date(2026, 7, 17)


@pytest.fixture(autouse=True)
def _db_universe(monkeypatch):
    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.get_universe_codes",
        lambda market: {"600519.SH"} if str(market).upper() == "CN" else {"AAPL.US"},
    )


def _watch(code: str, market: str, name: str = "watch"):
    return SimpleNamespace(code=code, market_type=market, name=name)


def test_market_data_scope_is_market_isolated_normalized_and_deduplicated():
    watchlist = MagicMock()
    watchlist.list_all.return_value = [
        _watch("aapl", "US"),
        _watch("AAPL.US", "US"),
        _watch("600519", "CN"),
        _watch("SH600519", "CN"),
        _watch("00700", "HK"),
    ]
    db_universe = SimpleNamespace(
        resolve_universe=lambda key: {
            "us_quant": [
                SimpleNamespace(code="AAPL.US"),
                SimpleNamespace(code="QQQ.US"),
                SimpleNamespace(code="SPY.US"),
            ],
            "cn_quant": [
                SimpleNamespace(code="600519.SH"),
                SimpleNamespace(code="159915.SZ"),
                SimpleNamespace(code="510300.SH"),
            ],
            "us_trend": [],
            "cn_trend": [],
            "us_etf_rotation": [],
            "cn_etf_rotation": [],
        }[key]
    )
    resolver = MarketDataScopeResolver(watchlist, db_universe)

    us = resolver.resolve("US")
    cn = resolver.resolve("CN")

    assert "AAPL.US" in us.universe_codes
    assert "600519.SH" not in us.universe_codes
    assert "600519.SH" in cn.universe_codes
    assert "AAPL.US" not in cn.universe_codes
    assert "700.HK" not in cn.universe_codes
    assert len([code for code in us.universe_codes if code == "AAPL.US"]) == 1
    assert cn.unsupported_symbols[0]["market"] == "HK"
    assert us.universe_codes & us.benchmark_dependency_codes == {"QQQ.US", "SPY.US"}
    assert cn.universe_codes & cn.benchmark_dependency_codes == {"159915.SZ", "510300.SH"}


def test_quant_market_configuration_selects_cn_close_and_defaults():
    us = get_quant_market_config("US")
    cn = get_quant_market_config("cn")

    assert us.default_universe == "us_quant"
    assert cn.default_universe == "cn_quant"
    assert cn.timezone == "Asia/Shanghai"
    assert cn.market_close_time == time(15, 0)
    assert default_universe_for_market("CN") == "cn_quant"
    assert cn.benchmark_dependencies == {"510300.SH", "159915.SZ"}
    assert cn.label_benchmark == "510300.SH"
    assert cn.regime_benchmarks == ("510300.SH", "510300.SH")
    assert cn.primary_benchmark == "510300.SH"
    assert cn.style_benchmark == "159915.SZ"
    assert us.label_benchmark == "SPY.US"
    assert us.regime_benchmarks == ("QQQ.US", "SPY.US")
    assert us.style_benchmark == "QQQ.US"
    assert not hasattr(cn, "risk_benchmark")
    assert DEFAULT_QUANT_UNIVERSES == {
        "US": "us_quant",
        "CN": "cn_quant",
    }


def test_market_universe_validation_accepts_only_fixed_market_keys():
    assert validate_universe_for_market("US", None) == "us_quant"
    assert validate_universe_for_market("US", "us_quant") == "us_quant"
    assert validate_universe_for_market("CN", None) == "cn_quant"
    assert validate_universe_for_market("CN", "cn_quant") == "cn_quant"
    for market, key in (
        ("US", "us_ai_semiconductor"),
        ("US", "us_quant_watchlist"),
        ("CN", "cn_quant_watchlist"),
        ("US", "custom_pool"),
        ("CN", "us_quant"),
    ):
        with pytest.raises(ValueError, match=r"only supported universe"):
            validate_universe_for_market(market, key)


def test_unsupported_universe_is_absent_from_seed_frontend_and_current_documentation():
    project_root = Path(__file__).resolve().parents[1]
    checked_paths = [
        project_root / "src" / "finance_analysis" / "database" / "seed.py",
        project_root / "docs" / "quant-research.md",
        *(project_root / "web" / "src").rglob("*.ts"),
        *(project_root / "web" / "src").rglob("*.vue"),
    ]

    assert all("us_ai_semiconductor" not in path.read_text(encoding="utf-8") for path in checked_paths)


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_quant_seed_initializes_unified_universe_definitions():
    database = DatabaseManager.get_instance()

    first = seed_quant_reference_data(database)
    second = seed_quant_reference_data(database)

    assert first == second
    assert set(first["universes"]) == {
        "cn_all_a",
        "cn_csi300",
        "cn_csi500",
        "cn_csi1000",
        "us_sp500",
        "cn_trend",
        "us_trend",
        "cn_etf_rotation",
        "us_etf_rotation",
        "cn_quant",
        "us_quant",
    }
    repository = QuantRepository(database)
    for market, key in DEFAULT_QUANT_UNIVERSES.items():
        universe = repository.get_universe(key)
        assert universe is not None
        assert universe.market == market
        assert universe.enabled is True
        assert universe.universe_type == "STRATEGY"
    unsupported = repository.get_universe("us_ai_semiconductor")
    if unsupported is not None:
        assert unsupported.enabled is False
        with pytest.raises(ValueError, match=r"only supported universe"):
            repository.create_dataset({"market": "US", "universe_id": unsupported.id})
        with pytest.raises(ValueError, match=r"only supported universe"):
            repository.create_model_run({"market": "US", "universe_id": unsupported.id})


def test_cn_pipeline_queries_only_cn_production_models(monkeypatch):
    repository = MagicMock()
    repository.get_universe.return_value = SimpleNamespace(id=9, key="cn_quant", market="CN", enabled=True)
    repository.daily_bar_codes.return_value = {"600519.SH"}
    repository.production_model.side_effect = [
        SimpleNamespace(id=11, model_key="cross_section_lgbm", model_version="cn-v1", artifact_uri="quant://cn/cs"),
        SimpleNamespace(id=12, model_key="time_series_lgbm", model_version="cn-v1", artifact_uri="quant://cn/ts"),
    ]
    exporter = MagicMock()
    exporter.export.return_value = SimpleNamespace(artifact_uri="quant://cn/dataset")
    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.DailyResearchService",
        lambda _repository, **_kwargs: SimpleNamespace(
            run=lambda *_args: {
                "eligible_codes": ["600519.SH"],
                "market_regime": SimpleNamespace(id=4, regime="neutral", market_score=0.5, max_equity_exposure=0.4),
                "warnings": [],
                "coverage": {"rankable_members": 1},
            }
        ),
    )
    requests, context = QuantDailyPipeline(
        repository=repository,
        cache=MagicMock(),
        exporter=exporter,
        symbol_repository=MagicMock(),
        artifact_store=MagicMock(),
    ).prepare("CN", trade_date=TRADE_DATE)

    assert repository.production_model.call_args_list[0].args == ("CN", "cross_section_lgbm")
    assert repository.production_model.call_args_list[1].args == ("CN", "time_series_lgbm")
    assert context["market"] == "CN"
    assert context["universe_key"] == "cn_quant"
    assert {request["artifact_uri"] for request in requests} == {"quant://cn/cs", "quant://cn/ts"}
    assert "price_mode" not in exporter.export.call_args.kwargs


@pytest.mark.parametrize(
    ("market", "universe"),
    (("US", "us_quant"), ("CN", "cn_quant")),
)
def test_scheduled_daily_pipeline_dispatches_the_fixed_market_universe(monkeypatch, market, universe):
    captured = {}

    class Pipeline:
        @staticmethod
        def prepare(market):
            return (
                [{"model_key": "cross_section_lgbm"}],
                {
                    "trade_date": str(TRADE_DATE),
                    "market": market,
                    "universe_key": validate_universe_for_market(market),
                },
            )

    def capture_chord_run(_self, header, body, _partial_args, **options):
        captured["header"] = header
        captured["body"] = body
        captured["options"] = options
        return SimpleNamespace(id="chord-id")

    monkeypatch.setattr(quant_daily_tasks, "QuantDailyPipeline", Pipeline)
    monkeypatch.setattr(_chord, "run", capture_chord_run)
    monkeypatch.setattr(quant_daily_tasks, "get_current_task_id", lambda: "parent-task-id")

    result = quant_daily_tasks._dispatch(market)

    assert result["market"] == market
    assert result["universe"] == universe
    assert len(captured["header"]) == 1
    assert captured["body"].task == "quant.daily.finalize"
    assert captured["body"].kwargs["context"]["lifecycle_task_id"] == "parent-task-id"
    assert captured["body"].kwargs["_skip_task_record"] is True
    assert captured["body"].options["queue"] == "analysis"
    errbacks = captured["body"].options["link_error"]
    assert len(errbacks) == 1
    assert errbacks[0]["task"] == "quant.daily.failed"
    assert "link_error" not in captured["options"]


def test_quant_errbacks_use_celery_legacy_task_id_signature() -> None:
    """Celery schedules one-argument errbacks with the failed task id.

    Two or more positional parameters make Celery invoke an errback inline as
    ``(request, exc, traceback)``, which conflicts with our pre-bound context.
    """
    from finance_analysis.tasks.celery.jobs.quant_training.tasks import fail_quant_model

    assert not arity_greater(quant_daily_tasks.fail_quant_daily.__header__, 1)
    assert not arity_greater(fail_quant_model.__header__, 1)


def test_quant_daily_final_status_records_partial_coverage(monkeypatch) -> None:
    lifecycle = MagicMock()
    monkeypatch.setattr(quant_daily_tasks, "get_task_lifecycle_service", lambda: lifecycle)
    context = {"market": "CN", "lifecycle_task_id": "parent-task-id"}
    result = {
        "status": "ready",
        "warnings": ["行情覆盖 234/302"],
        "coverage": {"skipped_members": 68},
    }

    quant_daily_tasks._mark_final_status(context, result=result)

    lifecycle.mark_completed.assert_called_once()
    call = lifecycle.mark_completed.call_args.kwargs
    assert call["task_id"] == "parent-task-id"
    assert call["metadata"].task_type == "scheduled_quant_daily_cn"
    assert call["result"] == result
    assert "已跳过部分缺失行情标的" in call["message"]


def test_cn_missing_production_model_never_falls_back_to_us():
    repository = MagicMock()
    repository.production_model.return_value = None
    pipeline = QuantDailyPipeline(
        repository=repository,
        cache=MagicMock(),
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
    )

    with pytest.raises(ModelNotPublishedError, match="CN cross_section_lgbm"):
        pipeline._production_model("CN", "cross_section_lgbm")

    repository.production_model.assert_called_once_with("CN", "cross_section_lgbm")


def test_cn_synthetic_sector_benchmark_uses_member_history_not_fake_symbol_data():
    dates = pd.bdate_range("2026-01-01", periods=70).date
    first = pd.DataFrame({"date": dates, "close": range(100, 170), "volume": 1000, "amount": 100_000})
    second = pd.DataFrame({"date": dates, "close": range(200, 270), "volume": 2000, "amount": 200_000})

    benchmark = build_synthetic_sector_benchmark({"A": first, "B": second})

    assert len(benchmark) == 70
    assert set(("date", "open", "high", "low", "close", "volume", "amount")).issubset(benchmark.columns)
    assert benchmark["close"].iloc[-1] > benchmark["close"].iloc[0]

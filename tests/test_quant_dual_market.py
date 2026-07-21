from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import delete, func, select

from finance_analysis.database.models.quant import QuantUniverse, QuantUniverseMember
from finance_analysis.database.models.stock import MarketDataSymbol
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.seed import seed_quant_reference_data
from finance_analysis.database.session import DatabaseManager
from finance_analysis.quant.exceptions import ModelNotPublishedError
from finance_analysis.quant.events.import_service import calculate_available_at
from finance_analysis.quant.markets import (
    DEFAULT_QUANT_UNIVERSES,
    default_universe_for_market,
    get_quant_market_config,
    validate_universe_for_market,
)
from finance_analysis.quant.pipeline.service import QuantDailyPipeline
from finance_analysis.quant.sectors.service import build_synthetic_sector_benchmark
from finance_analysis.quant.universe.service import FixedUniverseService, SectorClassification
from finance_analysis.stocks.market_scope import MarketDataScopeResolver
from finance_analysis.stocks.reference_data.stock_index import CSI300_STOCK_INDEX, SP500_STOCK_INDEX
from finance_analysis.tasks.celery.jobs.quant_daily import tasks as quant_daily_tasks


TRADE_DATE = date(2026, 7, 17)


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
    resolver = MarketDataScopeResolver(watchlist)

    us = resolver.resolve("US")
    cn = resolver.resolve("CN")

    assert "AAPL.US" in us.universe_codes
    assert "600519.SH" not in us.universe_codes
    assert "600519.SH" in cn.universe_codes
    assert "AAPL.US" not in cn.universe_codes
    assert "700.HK" not in cn.universe_codes
    assert len([code for code in us.universe_codes if code == "AAPL.US"]) == 1
    assert cn.unsupported_symbols[0]["market"] == "HK"
    assert not us.universe_codes & us.benchmark_dependency_codes
    assert not cn.universe_codes & cn.benchmark_dependency_codes


def test_fixed_quant_constituents_ignore_watchlist_and_benchmark_dependencies():
    watchlist = MagicMock()
    watchlist.list_all.return_value = [_watch("WATCHLIST-ONLY", "US")]
    market_data_scope = MarketDataScopeResolver(watchlist).resolve("US")

    us_members = FixedUniverseService.constituent_codes("US")
    cn_members = FixedUniverseService.constituent_codes("CN")

    assert "WATCHLIST-ONLY.US" in market_data_scope.universe_codes
    assert "WATCHLIST-ONLY.US" not in us_members
    assert us_members == {f"{code}.US" for code in SP500_STOCK_INDEX}
    assert cn_members == set(CSI300_STOCK_INDEX)
    assert not us_members & market_data_scope.benchmark_dependency_codes
    empty_watchlist = MagicMock()
    empty_watchlist.list_all.return_value = []
    assert not cn_members & MarketDataScopeResolver(empty_watchlist).resolve("CN").benchmark_dependency_codes


def test_quant_market_configuration_selects_cn_close_and_defaults():
    us = get_quant_market_config("US")
    cn = get_quant_market_config("cn")

    assert us.default_universe == "us_sp500"
    assert cn.default_universe == "cn_csi300"
    assert cn.timezone == "Asia/Shanghai"
    assert cn.market_close_time == time(15, 0)
    assert default_universe_for_market("CN") == "cn_csi300"
    assert cn.benchmark_dependencies == {"510300.SH", "510500.SH", "159915.SZ"}
    assert DEFAULT_QUANT_UNIVERSES == {
        "US": "us_sp500",
        "CN": "cn_csi300",
    }


def test_market_universe_validation_accepts_only_fixed_market_keys():
    assert validate_universe_for_market("US", None) == "us_sp500"
    assert validate_universe_for_market("US", "us_sp500") == "us_sp500"
    assert validate_universe_for_market("CN", None) == "cn_csi300"
    assert validate_universe_for_market("CN", "cn_csi300") == "cn_csi300"
    for market, key in (
        ("US", "us_ai_semiconductor"),
        ("US", "us_sp500_watchlist"),
        ("CN", "cn_csi300_watchlist"),
        ("US", "custom_pool"),
        ("CN", "us_sp500"),
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

    assert all(
        "us_ai_semiconductor" not in path.read_text(encoding="utf-8")
        for path in checked_paths
    )


def test_fixed_universe_migration_renames_in_place_and_ends_removed_members():
    project_root = Path(__file__).resolve().parents[1]
    migration = (
        project_root
        / "alembic"
        / "versions"
        / "0023_fixed_quant_universes.py"
    ).read_text(encoding="utf-8")
    normalized = migration.upper()

    assert '"old_key": "us_sp500_watchlist"' in migration
    assert '"old_key": "cn_csi300_watchlist"' in migration
    assert '"key": "us_sp500"' in migration
    assert '"key": "cn_csi300"' in migration
    assert "UPDATE QUANT_UNIVERSE" in normalized
    assert "UPDATE QUANT_UNIVERSE_MEMBER" in normalized
    assert "IS_DYNAMIC = FALSE" in normalized
    assert "SP500_STOCK_INDEX" in migration
    assert "CSI300_STOCK_INDEX" in migration
    assert "DELETE FROM QUANT_UNIVERSE" not in normalized
    assert "DELETE FROM QUANT_UNIVERSE_MEMBER" not in normalized
    assert "DROP TABLE" not in normalized


def test_cn_after_close_event_becomes_available_at_next_session_open():
    published = datetime(2026, 7, 17, 7, 1, tzinfo=timezone.utc)  # 15:01 Asia/Shanghai

    available = calculate_available_at(published, "CN")

    assert available == datetime(2026, 7, 20, 1, 30, tzinfo=timezone.utc)


def test_fixed_universe_uses_index_variables_and_reports_sector_coverage(monkeypatch):
    constituent_codes = frozenset({"600519.SH", "000001.SZ"})
    monkeypatch.setattr(
        FixedUniverseService,
        "constituent_codes",
        staticmethod(lambda _market: constituent_codes),
    )
    symbols = [SimpleNamespace(id=1, code="600519.SH"), SimpleNamespace(id=2, code="000001.SZ")]
    symbol_repository = MagicMock()
    symbol_repository.list_enabled_daily_by_codes.return_value = symbols
    repository = MagicMock()
    repository.upsert_universe.return_value = SimpleNamespace(id=8, config={})
    repository.latest_member_mappings.return_value = {}
    repository.sync_fixed_members.return_value = {"added": 2, "ended": 0, "updated": 0}

    class Classifier:
        @staticmethod
        def classify(_market, code):
            if code == "600519.SH":
                return SectorClassification("白酒", "CN-SECTOR-abc", "efinance_belong_board")
            return SectorClassification(None, None, "efinance_belong_board", "missing")

    result = FixedUniverseService(
        repository=repository,
        symbol_repository=symbol_repository,
        classifier=Classifier(),
    ).refresh("CN", TRADE_DATE)

    requested_market, requested_codes = symbol_repository.list_enabled_daily_by_codes.call_args.args
    universe_values = repository.upsert_universe.call_args.args[0]
    assert requested_market == "CN"
    assert set(requested_codes) == set(constituent_codes)
    assert universe_values["key"] == "cn_csi300"
    assert universe_values["name"] == "沪深300"
    assert universe_values["is_dynamic"] is False
    assert universe_values["config"] == {"constituent_source": "CSI300_STOCK_INDEX"}
    assert result["member_count"] == 2
    assert result["sector_mapping_coverage"] == 0.5
    assert result["missing_sector_mappings"] == [{"code": "000001.SZ", "reason": "missing"}]


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_quant_seed_only_enables_the_two_supported_fixed_universes():
    database = DatabaseManager.get_instance()

    first = seed_quant_reference_data(database)
    second = seed_quant_reference_data(database)

    assert first == second
    assert first["universes"] == ["us_sp500", "cn_csi300"]
    repository = QuantRepository(database)
    for market, key in DEFAULT_QUANT_UNIVERSES.items():
        universe = repository.get_universe(key)
        assert universe is not None
        assert universe.market == market
        assert universe.enabled is True
        assert universe.is_dynamic is False
    unsupported = repository.get_universe("us_ai_semiconductor")
    if unsupported is not None:
        assert unsupported.enabled is False
        with pytest.raises(ValueError, match=r"only supported universe"):
            repository.create_dataset({"market": "US", "universe_id": unsupported.id})
        with pytest.raises(ValueError, match=r"only supported universe"):
            repository.create_model_run({"market": "US", "universe_id": unsupported.id})


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_fixed_member_refresh_is_idempotent_and_preserves_ended_history():
    database = DatabaseManager.get_instance()
    suffix = uuid.uuid4().hex[:10].upper()
    universe_key = f"test_fixed_{suffix.lower()}"
    code = f"IDEMPOTENCY-{suffix}.US"
    universe_id = symbol_id = None
    try:
        with database.session_scope() as session:
            symbol = MarketDataSymbol(
                market="US",
                code=code,
                name="idempotency test",
                enabled=True,
                sync_daily=True,
                sync_minute=False,
            )
            universe = QuantUniverse(
                key=universe_key,
                name="idempotency test",
                market="US",
                enabled=True,
                is_dynamic=False,
                sector_benchmark_mode="member",
                config={},
            )
            session.add_all((symbol, universe))
            session.flush()
            symbol_id, universe_id = symbol.id, universe.id

        repository = QuantRepository(database)
        symbol_ref = SimpleNamespace(id=symbol_id)
        mapping = {
            symbol_id: {"sector_key": "technology", "sector_benchmark_code": "XLK.US"}
        }
        first = repository.sync_fixed_members(universe_id, [symbol_ref], mapping, TRADE_DATE)
        second = repository.sync_fixed_members(universe_id, [symbol_ref], mapping, TRADE_DATE)

        assert first == {"added": 1, "ended": 0, "updated": 0}
        assert second == {"added": 0, "ended": 0, "updated": 0}
        with database.get_session() as session:
            assert session.scalar(
                select(func.count(QuantUniverseMember.id)).where(
                    QuantUniverseMember.universe_id == universe_id
                )
            ) == 1

        ended = repository.sync_fixed_members(
            universe_id,
            [],
            {},
            TRADE_DATE.replace(day=20),
        )
        assert ended == {"added": 0, "ended": 1, "updated": 0}
        assert len(repository.active_members(universe_id, TRADE_DATE)) == 1
        assert repository.active_members(universe_id, TRADE_DATE.replace(day=20)) == []
    finally:
        if universe_id is not None or symbol_id is not None:
            with database.session_scope() as session:
                if universe_id is not None:
                    session.execute(
                        delete(QuantUniverseMember).where(
                            QuantUniverseMember.universe_id == universe_id
                        )
                    )
                    session.execute(delete(QuantUniverse).where(QuantUniverse.id == universe_id))
                if symbol_id is not None:
                    session.execute(
                        delete(MarketDataSymbol).where(MarketDataSymbol.id == symbol_id)
                    )


def test_cn_pipeline_queries_only_cn_production_models(monkeypatch):
    repository = MagicMock()
    repository.get_universe.return_value = SimpleNamespace(
        id=9, key="cn_csi300", market="CN", enabled=True
    )
    repository.active_members.return_value = [
        (
            SimpleNamespace(sector_key="白酒", sector_benchmark_code="CN-SECTOR-a"),
            SimpleNamespace(id=1, code="600519.SH"),
        )
    ]
    repository.daily_bar_codes.return_value = {"600519.SH"}
    repository.production_model.side_effect = [
        SimpleNamespace(id=11, model_key="cross_section_lgbm", model_version="cn-v1", artifact_uri="quant://cn/cs"),
        SimpleNamespace(id=12, model_key="time_series_lgbm", model_version="cn-v1", artifact_uri="quant://cn/ts"),
    ]
    exporter = MagicMock()
    exporter.export.return_value = SimpleNamespace(artifact_uri="quant://cn/dataset")
    monkeypatch.setattr(
        "finance_analysis.quant.pipeline.service.DailyResearchService",
        lambda _repository: SimpleNamespace(
            run=lambda *_args: {
                "eligible_codes": ["600519.SH"],
                "market_regime": SimpleNamespace(
                    id=4, regime="neutral", market_score=0.5, max_equity_exposure=0.4
                ),
                "warnings": [],
                "coverage": {"rankable_members": 1},
            }
        ),
    )
    universe_service = MagicMock()
    universe_service.refresh.return_value = {"market": "CN"}

    requests, context = QuantDailyPipeline(
        repository=repository,
        cache=MagicMock(),
        exporter=exporter,
        symbol_repository=MagicMock(),
        holding_repository=MagicMock(),
        universe_service=universe_service,
        artifact_store=MagicMock(),
        owner_uid=1,
    ).prepare("CN", trade_date=TRADE_DATE)

    assert repository.production_model.call_args_list[0].args == ("CN", "cross_section_lgbm")
    assert repository.production_model.call_args_list[1].args == ("CN", "time_series_lgbm")
    assert context["market"] == "CN"
    assert context["universe_key"] == "cn_csi300"
    assert {request["artifact_uri"] for request in requests} == {"quant://cn/cs", "quant://cn/ts"}
    assert exporter.export.call_args.kwargs["price_mode"] == "forward_adjusted"


@pytest.mark.parametrize(
    ("market", "universe"),
    (("US", "us_sp500"), ("CN", "cn_csi300")),
)
def test_scheduled_daily_pipeline_dispatches_the_fixed_market_universe(
    monkeypatch, market, universe
):
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

    class Chord:
        @staticmethod
        def apply_async(**_kwargs):
            return SimpleNamespace(id="chord-id")

    monkeypatch.setattr(quant_daily_tasks, "QuantDailyPipeline", Pipeline)
    monkeypatch.setattr(
        quant_daily_tasks.celery_app,
        "signature",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(quant_daily_tasks, "chord", lambda _header: Chord())
    monkeypatch.setattr(
        quant_daily_tasks,
        "finalize_quant_daily",
        SimpleNamespace(s=lambda **_kwargs: SimpleNamespace(set=lambda **__: None)),
    )
    monkeypatch.setattr(
        quant_daily_tasks,
        "fail_quant_daily",
        SimpleNamespace(s=lambda **_kwargs: SimpleNamespace(set=lambda **__: None)),
    )

    result = quant_daily_tasks._dispatch(market)

    assert result["market"] == market
    assert result["universe"] == universe


def test_cn_missing_production_model_never_falls_back_to_us():
    repository = MagicMock()
    repository.production_model.return_value = None
    pipeline = QuantDailyPipeline(
        repository=repository,
        cache=MagicMock(),
        exporter=MagicMock(),
        symbol_repository=MagicMock(),
        holding_repository=MagicMock(),
        universe_service=MagicMock(),
        owner_uid=1,
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

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import delete, func, select

from finance_analysis.database.models.quant import QuantUniverse, QuantUniverseMember
from finance_analysis.database.models.stock import MarketDataSymbol
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.database.session import DatabaseManager
from finance_analysis.quant.exceptions import ModelNotPublishedError
from finance_analysis.quant.events.import_service import calculate_available_at
from finance_analysis.quant.markets import default_universe_for_market, get_quant_market_config
from finance_analysis.quant.pipeline.service import QuantDailyPipeline
from finance_analysis.quant.sectors.service import build_synthetic_sector_benchmark
from finance_analysis.quant.universe.service import DynamicUniverseService, SectorClassification
from finance_analysis.stocks.market_scope import MarketDataScopeResolver


TRADE_DATE = date(2026, 7, 17)


def _watch(code: str, market: str, name: str = "watch"):
    return SimpleNamespace(code=code, market_type=market, name=name)


def test_shared_scope_is_market_isolated_normalized_and_deduplicated():
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


def test_quant_market_configuration_selects_cn_close_and_defaults():
    us = get_quant_market_config("US")
    cn = get_quant_market_config("cn")

    assert us.default_universe == "us_sp500_watchlist"
    assert cn.default_universe == "cn_csi300_watchlist"
    assert cn.timezone == "Asia/Shanghai"
    assert cn.market_close_time == time(15, 0)
    assert default_universe_for_market("CN") == "cn_csi300_watchlist"
    assert cn.benchmark_dependencies == {"510300.SH", "510500.SH", "159915.SZ"}


def test_cn_after_close_event_becomes_available_at_next_session_open():
    published = datetime(2026, 7, 17, 7, 1, tzinfo=timezone.utc)  # 15:01 Asia/Shanghai

    available = calculate_available_at(published, "CN")

    assert available == datetime(2026, 7, 20, 1, 30, tzinfo=timezone.utc)


def test_dynamic_universe_uses_exact_shared_scope_and_reports_sector_coverage():
    scope = SimpleNamespace(
        universe_codes=frozenset({"600519.SH", "000001.SZ"}),
        benchmark_dependency_codes=frozenset({"510300.SH"}),
    )
    scope_resolver = MagicMock()
    scope_resolver.resolve.return_value = scope
    symbols = [SimpleNamespace(id=1, code="600519.SH"), SimpleNamespace(id=2, code="000001.SZ")]
    symbol_repository = MagicMock()
    symbol_repository.list_enabled_daily_by_codes.return_value = symbols
    repository = MagicMock()
    repository.upsert_universe.return_value = SimpleNamespace(id=8, config={})
    repository.latest_member_mappings.return_value = {}
    repository.sync_dynamic_members.return_value = {"added": 2, "ended": 0, "updated": 0}

    class Classifier:
        @staticmethod
        def classify(_market, code):
            if code == "600519.SH":
                return SectorClassification("白酒", "CN-SECTOR-abc", "efinance_belong_board")
            return SectorClassification(None, None, "efinance_belong_board", "missing")

    result = DynamicUniverseService(
        repository=repository,
        symbol_repository=symbol_repository,
        scope_resolver=scope_resolver,
        classifier=Classifier(),
    ).refresh("CN", TRADE_DATE)

    requested_market, requested_codes = symbol_repository.list_enabled_daily_by_codes.call_args.args
    assert requested_market == "CN"
    assert set(requested_codes) == set(scope.universe_codes)
    assert result["member_count"] == 2
    assert result["sector_mapping_coverage"] == 0.5
    assert result["missing_sector_mappings"] == [{"code": "000001.SZ", "reason": "missing"}]


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_dynamic_member_refresh_is_idempotent_and_preserves_ended_history():
    database = DatabaseManager.get_instance()
    suffix = uuid.uuid4().hex[:10].upper()
    universe_key = f"test_dynamic_{suffix.lower()}"
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
                is_dynamic=True,
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
        first = repository.sync_dynamic_members(universe_id, [symbol_ref], mapping, TRADE_DATE)
        second = repository.sync_dynamic_members(universe_id, [symbol_ref], mapping, TRADE_DATE)

        assert first == {"added": 1, "ended": 0, "updated": 0}
        assert second == {"added": 0, "ended": 0, "updated": 0}
        with database.get_session() as session:
            assert session.scalar(
                select(func.count(QuantUniverseMember.id)).where(
                    QuantUniverseMember.universe_id == universe_id
                )
            ) == 1

        ended = repository.sync_dynamic_members(
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
    repository.get_universe.return_value = SimpleNamespace(id=9, market="CN")
    repository.active_members.return_value = [
        (SimpleNamespace(sector_key="白酒", sector_benchmark_code="CN-SECTOR-a"), SimpleNamespace(id=1, code="600519.SH"))
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
        owner_uid=1,
    ).prepare("CN", trade_date=TRADE_DATE)

    assert repository.production_model.call_args_list[0].args == ("CN", "cross_section_lgbm")
    assert repository.production_model.call_args_list[1].args == ("CN", "time_series_lgbm")
    assert context["market"] == "CN"
    assert context["universe_key"] == "cn_csi300_watchlist"
    assert {request["artifact_uri"] for request in requests} == {"quant://cn/cs", "quant://cn/ts"}


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

"""Offline contract, accounting, publication and read-boundary regression tests."""

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.dragon_tiger import normalize_source
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider, FuyaoError
from finance_analysis.dragon_tiger_flow.calculator import calculate, allocate, split_amount, concept_detail
from finance_analysis.dragon_tiger_flow.service import DragonTigerFlowService, DragonTigerReadinessError
from finance_analysis.database.models.dragon_tiger_flow import DragonTigerFlowBatch as Batch
from finance_analysis.database.repositories.dragon_tiger_flow import DragonTigerFlowRepository
from finance_analysis.interfaces.api.v1.endpoints import dragon_tiger_flow as api

DAY = date(2026, 9, 21)


def row(symbol="600001.SH", value="100.01", period=1, **kw):
    return {
        "thscode": symbol,
        "name": symbol,
        "range_days": period,
        "net_value": value,
        "buy_value": "150.01",
        "sell_value": "50",
        "org_net_value": "20.00",
        "hot_money_net_value": "30.00",
        "concept_list": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
        **kw,
    }


def source(rows=None, board="all", day=DAY, groups=None):
    rows = [row()] if rows is None else rows
    return {
        "trade_date": day.isoformat(),
        "board_type": board,
        "timestamp": 1789920000000,
        "count": len(rows),
        "stock_count": len({r["thscode"] for r in rows}),
        "stock_items": rows if board != "hot_money" else [],
        "hot_money_items": groups or [],
    }


def sources(rows=None, day=DAY):
    return {b: normalize_source(source(rows, b, day), day, b) for b in ("all", "org", "hot_money")}


def batch(rows=None, day=DAY, batch_id="1"):
    return {"batch_id": batch_id, "generated_at": utc_now().isoformat(), "sources": sources(rows, day)}


@pytest.mark.parametrize("value", ["100.01", "-100.01", "0.01", "-0.01", "0"])
def test_exact_cent_conservation(value):
    parts = split_amount(value, 7)
    assert sum(map(Decimal, parts)) == Decimal(value)
    assert max(map(Decimal, parts)) - min(map(Decimal, parts)) <= Decimal("0.01")


def test_period_duplicates_concepts_and_unknown():
    rows = [row(), row(), row(period=3, value="999"), row("600002.SH", "-15", concept_list=[])]
    normalized = normalize_source(source(rows), DAY, "all")
    assert normalized["quality"]["duplicates_removed"] == 1
    result = calculate({DAY: {**batch(), "sources": {"all": normalized}}}, [DAY])
    assert result["summary"]["net_value"] == 85.01
    assert sum(c["net_value"] for c in result["concepts"]) == pytest.approx(85.01)
    assert any(c["name"] == "未分类" for c in result["concepts"])
    assert result["summary"]["stock_count"] == 2
    assert calculate({DAY: batch(rows)}, [DAY], period=3)["summary"]["net_value"] == 999


@pytest.mark.parametrize("patch", [{"net_value": "NaN"}, {"range_days": None}, {"net_value": True}, {"thscode": "123"}])
def test_invalid_records_rejected(patch):
    with pytest.raises(ValueError):
        normalize_source(source([row(**patch)]), DAY, "all")


def test_conflicts_not_summed_or_silently_discarded():
    with pytest.raises(ValueError, match="Conflicting"):
        normalize_source(source([row(), row(value="200")]), DAY, "all")
    bad = source()
    bad["count"] += 1
    with pytest.raises(ValueError, match="Incomplete"):
        normalize_source(bad, DAY, "all")


@pytest.mark.parametrize("board", ["all", "org", "hot_money"])
def test_extended_periods_are_audited_without_entering_observations(board):
    rows = [row(), row(period=3), row(period=10), row("600002.SH", period=30)]
    raw = source(rows, board, groups=[{"name": "席位A", "rows": rows}])
    if board != "hot_money":
        raw["hot_money_items"] = []
    normalized = normalize_source(raw, DAY, board)
    key = "details" if board == "hot_money" else "rows"
    assert [r["range_days"] for r in normalized[key]] == [1, 3]
    assert [r["range_days"] for r in normalized["excluded_" + key]] == [10, 30]
    assert normalized["upstream_count"] == 4
    assert normalized["upstream_stock_count"] == 2
    assert normalized["quality"]["excluded_period_counts"] == {"10": 1, "30": 1}


@pytest.mark.parametrize("board", ["all", "org", "hot_money"])
@pytest.mark.parametrize("patch", [{"net_value": "NaN"}, {"value": "200"}])
def test_extended_periods_still_validate_fields_and_conflicts(board, patch):
    rows = [row(period=10), row(period=10, **patch)]
    raw = source(rows, board, groups=[{"name": "席位A", "rows": rows}] if board == "hot_money" else [])
    with pytest.raises(ValueError):
        normalize_source(raw, DAY, board)


@pytest.mark.parametrize("period", [None, True, "10", 10.0, 0, -1, 2, 5, 20, 60])
def test_unknown_or_invalid_periods_remain_errors(period):
    with pytest.raises(ValueError, match="period"):
        normalize_source(source([row(period=period)]), DAY, "all")


def test_extended_periods_do_not_hide_count_mismatches():
    for field in ("count", "stock_count"):
        raw = source([row(), row("600002.SH", period=30)])
        raw[field] -= 1
        with pytest.raises(ValueError, match="Incomplete"):
            normalize_source(raw, DAY, "all")


def test_hot_money_detail_is_limited_not_stock_total():
    groups = [
        {"name": "席位A", "rows": [row(hot_money_item_net_value="5")]},
        {"name": "席位B", "rows": [row(hot_money_item_net_value="7")]},
    ]
    raw = source(board="hot_money", groups=groups)
    raw["count"] = 80
    raw["stock_count"] = 70
    detail = normalize_source(raw, DAY, "hot_money")
    b = batch()
    b["sources"]["hot_money"] = detail
    result = calculate({DAY: b}, [DAY], board="hot_money")
    assert result["summary"]["net_value"] == 30  # not repeated stock-wide 60 or sample-only 12
    assert result["summary"]["buy_value"] is None
    assert len(result["hot_money_details"]) == 2
    assert result["attribution"] == "independent_overlapping_categories"
    assert calculate({DAY: b}, [DAY], board="org")["summary"]["net_value"] == 20


def test_missing_is_not_zero_and_window_rebases():
    d2, d3 = DAY + timedelta(days=1), DAY + timedelta(days=2)
    batches = {DAY: batch(day=DAY), d3: batch(day=d3)}
    result = calculate(batches, [DAY, d2, d3])
    assert result["missing_dates"] == [d2.isoformat()]
    assert result["summary"]["net_value"] is None
    assert result["concepts"][0]["values"][1:] == [None, None]
    narrow = calculate(batches, [d3])
    assert narrow["summary"]["net_value"] == 100.01
    batches[d2] = batch([], d2)
    result = calculate(batches, [DAY, d2, d3])
    assert result["complete"] and result["summary"]["net_value"] == 200.02
    assert result["concepts"][0]["values"][0] == result["concepts"][0]["values"][1]
    assert result["revision"] != narrow["revision"]
    assert concept_detail(result, result["concepts"][0]["id"])["stocks"][0]["net_value"] is not None


def test_unknown_category_and_concepts_dedup():
    b = batch([row(org_net_value=None, hot_money_net_value=None, concept_list=[{"name": " A "}, {"name": "A"}])])
    result = calculate({DAY: b}, [DAY])
    assert result["summary"]["org_net_value"] is None
    assert len(result["concepts"]) == 1
    result = calculate({DAY: b}, [DAY], board="hot_money")
    assert result["excluded_undisclosed_count"] == 1
    assert result["summary"]["net_value"] is None
    assert result["concepts"] == []
    assert allocate(b["sources"]["all"]["rows"])[0]["allocation_count"] == 1


def test_provider_contract_and_no_legacy_cache():
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"code": 0, "data": source(board=request.url.params["board_type"])})

    provider = FuyaoProvider(api_key="test", transport=httpx.MockTransport(handler))
    provider.cached("dragon_tiger:2026-09-21", 600, lambda: {"stock_items": [{"thscode": "legacy"}]})
    assert provider.get_dragon_tiger_board(DAY)["rows"][0]["net_value"] == "100.01"
    assert provider.get_dragon_tiger_board(DAY, "org")["board"] == "org"
    assert calls == [{"date": "2026-09-21", "board_type": "all"}, {"date": "2026-09-21", "board_type": "org"}]
    provider = FuyaoProvider(
        api_key="test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 1002}))
    )
    with pytest.raises(FuyaoError):
        provider.get_dragon_tiger_board(DAY)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Batch.__table__.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

    yield DB()
    engine.dispose()


def test_extended_periods_publish_and_preserve_public_schema(db, monkeypatch):
    from finance_analysis.interfaces.api.v1.schemas.dragon_tiger_flow import Overview

    rows = [row(), row(period=3, value="300"), row(period=10, value="10000"), row(period=30, value="30000")]

    def handler(request):
        board = request.url.params["board_type"]
        groups = [{"name": "席位A", "rows": rows}] if board == "hot_money" else []
        return httpx.Response(200, json={"code": 0, "data": source(rows, board, groups=groups)})

    provider = FuyaoProvider(api_key="test", transport=httpx.MockTransport(handler))
    repo = DragonTigerFlowRepository(db)
    monkeypatch.setattr("finance_analysis.dragon_tiger_flow.service.validate_day", lambda day: None)
    monkeypatch.setattr("finance_analysis.database.repositories.dragon_tiger_flow.sessions_through", lambda d, n: [d])
    assert DragonTigerFlowService(repo, provider).run(DAY)["status"] == "completed"
    assert repo.has_complete(DAY)
    with db.get_session() as session:
        stored = session.get(Batch, DAY).payload["sources"]
        assert len(stored["all"]["excluded_rows"]) == 2
        assert len(stored["org"]["excluded_rows"]) == 2
        assert len(stored["hot_money"]["excluded_details"]) == 2
    for board, amounts in (("all", (100.01, 300)), ("org", (20, 20)), ("hot_money", (30, 30))):
        for period, expected in zip((1, 3), amounts):
            result = repo.window(DAY, board=board, period=period)
            Overview.model_validate(result)
            assert result["complete"]
            assert result["summary"]["net_value"] == expected
            assert all(r["range_days"] == period for r in result["evidence"] + result["hot_money_details"])
            quality = result["source_quality"][0]["sources"][board]["quality"]
            assert quality["excluded_period_counts"] == {"10": 1, "30": 1}


def test_extended_only_source_is_complete_empty_observation():
    result = calculate({DAY: batch([row(period=10), row(period=30)])}, [DAY])
    assert result["complete"]
    assert result["summary"]["net_value"] == 0
    assert result["summary"]["stock_count"] == 0
    assert result["evidence"] == []


def test_atomic_publication_and_read_only_window(db, monkeypatch):
    repo = DragonTigerFlowRepository(db)
    repo.publish(DAY, sources(), {}, utc_now())
    first = repo.window(DAY, 5, period=3)
    assert first["summary"]["net_value"] == 0  # no 3-day records, verified empty scope
    with pytest.raises(ValueError):
        repo.publish(DAY, {}, {}, utc_now())
    with pytest.raises(ValueError, match="regression"):
        repo.publish(DAY, {"all": sources()["all"]}, {"org": "failed"}, utc_now())
    assert repo.window(DAY, 5, period=3)["revision"] == first["revision"]
    repo.publish(DAY, sources([row(value="120")]), {}, utc_now())
    with db.get_session() as session:
        assert len(list(session.scalars(select(Batch)))) == 1
    assert repo.has_complete(DAY)
    assert repo.dates()[0]["trade_date"] == DAY
    monkeypatch.setattr("finance_analysis.database.repositories.dragon_tiger_flow.sessions_through", lambda d, n: [d])
    result = repo.window(DAY)
    assert result["summary"]["net_value"] == 120
    assert result["revision"] != first["revision"]
    assert repo.window(DAY + timedelta(days=1))["missing_dates"] == ["2026-09-22"]


def test_service_network_outside_publish_and_core_failure(db, monkeypatch):
    monkeypatch.setattr("finance_analysis.dragon_tiger_flow.service.validate_day", lambda day: None)
    repo = DragonTigerFlowRepository(db)

    class Market:
        def get_dragon_tiger_board(self, day, board):
            return sources()[board]

    service = DragonTigerFlowService(repo, Market())
    assert service.run(DAY)["status"] == "completed"

    class Failed:
        def get_dragon_tiger_board(self, *args):
            raise FuyaoError("upstream unavailable")

    with pytest.raises(DragonTigerReadinessError):
        DragonTigerFlowService(repo, Failed()).run(DAY)
    assert repo.has_complete(DAY)


def test_api_validation_read_boundary_and_revision(db, monkeypatch):
    repo = DragonTigerFlowRepository(db)
    repo.publish(DAY, sources(), {}, utc_now())
    monkeypatch.setattr("finance_analysis.database.repositories.dragon_tiger_flow.sessions_through", lambda d, n: [d])
    monkeypatch.setattr(api, "expected_date", lambda: DAY)
    app = FastAPI()
    app.include_router(api.router, prefix="/flow")
    app.dependency_overrides[api.get_repository] = lambda: repo
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app)
    result = client.get("/flow/overview?end_date=2026-09-21&days=20&range_days=1")
    assert result.status_code == 200, result.text
    data = result.json()
    detail = client.get(
        "/flow/concepts/" + data["concepts"][0]["id"] + "?end_date=2026-09-21&revision=" + data["revision"]
    )
    assert detail.status_code == 200
    assert client.get("/flow/stocks/600001.SH?end_date=2026-09-21&revision=old").status_code == 409
    assert client.get("/flow/overview?days=1").status_code == 200
    assert client.get("/flow/overview?days=2").status_code == 422
    assert client.get("/flow/overview?days=100").status_code == 422
    assert client.get("/flow/overview?board=bogus").status_code == 422
    assert client.get("/flow/stocks/600999.SH?end_date=2026-09-21").status_code == 404
    app.dependency_overrides[api.require_admin] = lambda: (_ for _ in ()).throw(
        api.HTTPException(403, "Admin required")
    )
    assert client.post("/flow/run", json={}).status_code == 403
    app.dependency_overrides[api.require_admin] = lambda: SimpleNamespace(id=1)
    assert client.post("/flow/run", json={"backfill_days": 32}).status_code == 422
    assert client.post("/flow/run", json={"backfill_days": 5, "trade_date": "2026-09-21"}).status_code == 422


def test_migration_upgrade_downgrade_matches_model():
    path = Path(__file__).parents[2] / "alembic/versions/0064_dragon_tiger_flow.py"
    spec = importlib.util.spec_from_file_location("migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()
            from sqlalchemy import inspect

            columns = inspect(connection).get_columns(Batch.__tablename__)
            assert {c["name"] for c in columns} == set(Batch.__table__.columns.keys())
            module.downgrade()
            assert Batch.__tablename__ not in inspect(connection).get_table_names()
    engine.dispose()


def test_fractional_cent_normalization_and_unknown_concentration():
    b = batch([row(value="100.015"), row("600002.SH", "5", org_net_value=None)])
    result = calculate({DAY: b}, [DAY])
    assert result["summary"]["net_value"] == 105.02
    assert sum(c["net_value"] for c in result["concepts"]) == pytest.approx(105.02)
    assert calculate({DAY: b}, [DAY], board="org")["summary"]["top5_concentration"] is None


def test_bounded_backfill_and_optional_failures_are_reported(db, monkeypatch):
    monkeypatch.setattr("finance_analysis.dragon_tiger_flow.service.validate_day", lambda day: None)
    monkeypatch.setattr("finance_analysis.dragon_tiger_flow.service.expected_date", lambda: DAY)
    monkeypatch.setattr("finance_analysis.dragon_tiger_flow.service.sessions_through", lambda d, n: [DAY])
    repo = DragonTigerFlowRepository(db)

    class Partial:
        def get_dragon_tiger_board(self, day, board):
            if board == "org":
                raise FuyaoError("unavailable")
            return sources()[board]

    service = DragonTigerFlowService(repo, Partial())
    with pytest.raises(ValueError):
        service.run(backfill_days=32)
    result = service.run(backfill_days=20)
    assert result["status"] == "partial"
    assert not repo.has_complete(DAY)
    assert repo.dates()[0]["boards"] == ["all", "hot_money"]
    assert service.run(backfill_days=20)["days"][0]["status"] == "partial"
    with pytest.raises(DragonTigerReadinessError):
        service.run(DAY)


def test_routing_is_cn_only_and_schedule_is_tracked():
    from finance_analysis.integrations.market_data.registry import ProviderRegistry, DRAGON_TIGER_BOARD
    from finance_analysis.integrations.market_data.service import MarketDataService
    from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition, build_task_routes

    registry = ProviderRegistry()
    registry.register(
        "fuyao", SimpleNamespace(get_dragon_tiger_board=lambda d, b: (d, b)), capabilities={DRAGON_TIGER_BOARD}
    )
    market = MarketDataService(registry=registry)
    assert market.get_dragon_tiger_board(DAY, "org") == (DAY, "org")
    with pytest.raises(ValueError):
        market.get_dragon_tiger_board(DAY, market="US")
    definition = require_scheduled_task_definition("dragon_tiger_flow_cn")
    assert definition.schedules[0].hour == "19"
    assert definition.schedules[0].minute == "30"
    assert definition.timezone == "Asia/Shanghai"
    assert build_task_routes()[definition.celery_task_name]["queue"] == "analysis"


def test_missing_selected_source_retains_failure_metadata():
    b = batch()
    del b["sources"]["org"]
    b["errors"] = {"org": "FuyaoError"}
    result = calculate({DAY: b}, [DAY], board="org")
    assert not result["complete"]
    assert result["summary"]["net_value"] is None
    assert result["source_quality"][0]["errors"] == {"org": "FuyaoError"}


def test_real_task_definition_skips_before_session_and_retries_readiness(monkeypatch):
    from finance_analysis.tasks.celery.jobs.dragon_tiger_flow import tasks
    from finance_analysis.tasks.lifecycle import TaskSkipped

    # Unwrap Celery autoretry + lifecycle: no DB lock or broker needed for the domain boundary.
    import inspect

    function = inspect.unwrap(tasks.run_dragon_tiger_flow_cn.run)
    monkeypatch.setattr(tasks, "is_market_open", lambda *a: False)
    with pytest.raises(TaskSkipped):
        function()
    definition = tasks.run_dragon_tiger_flow_cn
    assert definition.retry_kwargs["max_retries"] == 3
    assert definition.default_retry_delay == 600


def test_admin_default_resolves_closed_day_before_queueing(monkeypatch):
    from finance_analysis.tasks.celery.jobs.dragon_tiger_flow import tasks

    calls = []
    monkeypatch.setattr(api, "expected_date", lambda: DAY)
    monkeypatch.setattr(
        tasks.run_dragon_tiger_flow_cn,
        "apply_async",
        lambda **kwargs: (calls.append(kwargs), SimpleNamespace(id="test-job"))[1],
    )
    result = api.run(api.RunRequest(), SimpleNamespace(id=7))
    assert result["task_id"] == "test-job"
    assert calls[0]["kwargs"]["trade_date"] == "2026-09-21"
    assert calls[0]["kwargs"]["_triggered_by_uid"] == 7
    assert calls[0]["queue"] == "analysis"

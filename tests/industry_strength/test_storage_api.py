"""Real SQL reads/migration, PostgreSQL upsert execution, and authenticated API contracts."""

import importlib.util
import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from finance_analysis.database.models.industry_strength import IndustryStrengthSnapshot as Snapshot
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.interfaces.api.v1.endpoints import industry_strength as endpoint
from finance_analysis.interfaces.api.deps import require_current_user

DAY = date(2026, 9, 16)
OLD = date(2026, 9, 15)


class Database:
    def __init__(self, bind=None):
        self.bind = bind if bind is not None else create_engine("sqlite://")

    @contextmanager
    def get_session(self):
        with Session(self.bind) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.bind) as session, session.begin():
            yield session


def payload(code="881101.TI", day=DAY, rank=1):
    now = datetime.now(timezone.utc)
    return dict(
        trade_date=day,
        industry_code=code,
        industry_name=code,
        state="NEUTRAL",
        strength_rank=rank,
        strength_score=100 - rank,
        rs_5d=rank / 100,
        constituent_count=5, daily_valid_count=5, up_count=4, down_count=1, flat_count=0,
        ma5_valid_count=4, above_ma5_count=3, above_ma5_ratio=None,
        ma20_valid_count=3, above_ma20_count=2, above_ma20_ratio=None,
        data_timestamp=now,
        members_observed_at=now,
        quality={"member_codes": ["600001.SH"], "catalog_count": 2},
        created_at=now,
        updated_at=now,
    )


def migration():
    path = Path(__file__).parents[2] / "alembic/versions/0054_industry_strength.py"
    spec = importlib.util.spec_from_file_location("industry_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_and_real_read_queries():
    db = Database()
    m = migration()
    with db.bind.begin() as conn:
        m.op = Operations(MigrationContext.configure(conn))
        m.upgrade()
        assert inspect(conn).get_unique_constraints(Snapshot.__tablename__)[0]["column_names"] == [
            "trade_date",
            "industry_code",
        ]
        assert {c["name"] for c in inspect(conn).get_columns(Snapshot.__tablename__)} == set(
            Snapshot.__table__.columns.keys()
        )
        conn.execute(Snapshot.__table__.insert(), [payload(), payload("881102.TI", rank=2), payload(day=OLD, rank=3)])
    repo = IndustryStrengthRepository(db)
    assert repo.dates() == [DAY, OLD]
    assert [r["strength_rank"] for r in repo.ranking()] == [1, 2]
    assert repo.ranking(OLD)[0]["strength_rank"] == 3
    assert repo.ranking(sort_by="rs_5d")[0]["strength_rank"] == 2
    assert repo.ranking(sort_by="rs_5d", descending=False, limit=1)[0]["strength_rank"] == 1
    assert repo.ranking(date(2020, 1, 1)) == []
    assert len(repo.history(DAY, ["881101.TI"])) == 2
    assert repo.history(OLD)[0]["trade_date"] == OLD
    with db.bind.begin() as conn:
        m.op = Operations(MigrationContext.configure(conn))
        m.downgrade()
        assert Snapshot.__tablename__ not in inspect(conn).get_table_names()


def test_postgresql_upsert_rerun_removes_stale_rows_and_keeps_other_days():
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("dedicated TEST_POSTGRES_URL required")
    engine = create_engine(url)
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            schema = "test_industry_" + uuid4().hex
            conn.execute(text(f"CREATE SCHEMA {schema}"))
            conn.execute(text(f"SET LOCAL search_path TO {schema}"))
            m = migration()
            m.op = Operations(MigrationContext.configure(conn))
            m.upgrade()
            repo = IndustryStrengthRepository(Database(conn))
            repo.save(OLD, [payload(day=OLD)])
            repo.save(DAY, [payload(), payload("881102.TI", rank=2)])
            first = repo.ranking()[0]
            repo.save(DAY, [payload(rank=4)])
            second = repo.ranking()[0]
            assert first["id"] == second["id"] and first["created_at"] == second["created_at"]
            assert second["strength_rank"] == 4 and len(repo.ranking()) == 1
            assert repo.dates() == [DAY, OLD]
            assert len(repo.history(DAY)) == 2
            with pytest.raises(ValueError):
                repo.save(DAY, [])
        finally:
            transaction.rollback()
    engine.dispose()


class FakeRepository:
    def __init__(self):
        self.calls = []

    def ranking(self, day=None, sort_by="strength_rank", descending=None, limit=500):
        self.calls.append((day, sort_by, descending, limit))
        return [payload(day=day or DAY)] if day != date(2020, 1, 1) else []

    def dates(self, *a, **kw):
        return [DAY, OLD]

    def history(self, day, codes=None, limit=20):
        return [payload(day=OLD), payload()]


@pytest.fixture
def api():
    app = FastAPI()
    repo = FakeRepository()
    app.include_router(endpoint.router, prefix="/industry-strength")
    app.dependency_overrides[require_current_user] = lambda: object()
    app.dependency_overrides[endpoint.get_repository] = lambda: repo
    with TestClient(app) as client:
        yield client, repo


def test_api_latest_date_explicit_date_sorting_and_detail(api):
    client, repo = api
    response = client.get("/industry-strength/ranking")
    assert response.status_code == 200 and response.json()["trade_date"] == str(DAY)
    assert "member_codes" not in response.json()["items"][0]["quality"]
    item = response.json()["items"][0]
    assert (item["daily_valid_count"], item["ma5_valid_count"], item["ma20_valid_count"]) == (5, 4, 3)
    assert item["above_ma20_ratio"] is None
    assert "valid_constituent_count" not in item
    response = client.get("/industry-strength/ranking?trade_date=2026-09-15&sort_by=rs_5d&limit=1&descending=false")
    assert response.status_code == 200 and repo.calls[-1] == (OLD, "rs_5d", False, 1)
    assert client.get("/industry-strength/ranking?sort_by=DROP").status_code == 422
    assert client.get("/industry-strength/ranking?limit=0").status_code == 422
    assert client.get("/industry-strength/ranking?trade_date=2020-01-01").json()["items"] == []
    assert client.get("/industry-strength/dates").json() == [str(DAY), str(OLD)]
    assert client.get("/industry-strength/881101.TI?trade_date=2026-09-15").json()["current"]["trade_date"] == str(OLD)
    assert client.get("/industry-strength/unknown").status_code == 404
    assert client.get("/industry-strength/history").json()["dates"] == [str(OLD), str(DAY)]
    assert client.get("/industry-strength/history?trade_date=2020-01-01").json()["items"] == []


def test_api_constituents_reads_only_repository(api, monkeypatch):
    from finance_analysis.integrations.market_data.service import MarketDataService
    from finance_analysis.industry_strength.service import IndustryStrengthService
    from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider
    from finance_analysis.database.repositories.trend_following import TrendFollowingRepository

    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP constituents must only read persisted constituent rows")

    for target in (MarketDataService, IndustryStrengthService, FuyaoProvider, TrendFollowingRepository):
        monkeypatch.setattr(target, "__init__", forbidden)
    client, repo = api
    calls = []
    def read(code):
        calls.append(code)
        return {
            "industry_code": code, "updated_at": None,
            "constituent_count": 1, "daily_valid_count": 0,
            "ma5_valid_count": 0, "above_ma5_count": 0, "ma20_valid_count": 0, "above_ma20_count": 0,
            "items": [{"code": "600001.SH", "name": "股票", "price": None, "change_pct": None,
                       "volume": None, "amount": None, "above_ma5": None, "above_ma20": None,
                       "trend_rank": None}],
        }
    repo.constituents = read
    response = client.get("/industry-strength/881199.TI/constituents")
    assert response.status_code == 200
    assert response.json()["items"][0]["trend_rank"] is None
    assert "trade_date" not in response.json()
    assert calls == ["881199.TI"] and repo.calls == []


def test_api_requires_authentication():
    app = FastAPI()
    app.include_router(endpoint.router)
    with TestClient(app) as client:
        assert client.get("/dates").status_code == 401


def test_history_migration_preserves_rows_and_accepts_missing_observation():
    db = Database()
    original = migration()
    path = Path(__file__).parents[2] / "alembic/versions/0055_industry_history.py"
    spec = importlib.util.spec_from_file_location("industry_history_migration", path)
    history_migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(history_migration)
    with db.bind.begin() as conn:
        operations = Operations(MigrationContext.configure(conn))
        original.op = operations
        original.upgrade()
        conn.execute(Snapshot.__table__.insert(), payload())
        history_migration.op = operations
        history_migration.upgrade()
        conn.execute(Snapshot.__table__.insert(), {**payload(day=OLD), "members_observed_at": None})
    repo = IndustryStrengthRepository(db)
    assert repo.ranking(DAY)[0]["members_observed_at"] is not None
    historical = repo.ranking(OLD)[0]
    assert historical["members_observed_at"] is None
    from finance_analysis.interfaces.api.v1.schemas.industry_strength import IndustrySnapshot
    assert IndustrySnapshot.model_validate(historical).members_observed_at is None


def constituent_migration():
    path = Path(__file__).parents[2] / "alembic/versions/0058_industry_constituents.py"
    spec = importlib.util.spec_from_file_location("industry_constituent_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def member(code="600001.SH", industry="881101.TI", rank=38):
    return dict(industry_code=industry, stock_code=code, stock_name=code, price=100,
                change_pct=.01, volume=10, amount=1000, above_ma5=True, above_ma20=None, trend_rank=rank)


def test_constituent_migration_schema_and_database_only_reads():
    from finance_analysis.database.models.industry_strength import IndustryStrengthConstituent as Member
    db = Database()
    m = constituent_migration()
    with db.bind.begin() as conn:
        m.op = Operations(MigrationContext.configure(conn))
        m.upgrade()
        schema = inspect(conn)
        columns = schema.get_columns(Member.__tablename__)
        assert {c["name"] for c in columns} == set(Member.__table__.columns.keys())
        assert "trade_date" not in {c["name"] for c in columns}
        assert next(c for c in columns if c["name"] == "trend_rank")["nullable"]
        assert schema.get_foreign_keys(Member.__tablename__) == []
        assert schema.get_unique_constraints(Member.__tablename__)[0]["column_names"] == ["industry_code", "stock_code"]
        conn.execute(Member.__table__.insert(), [
            member(), member("600002.SH", rank=None), member(industry="881102.TI"),
        ])
    repo = IndustryStrengthRepository(db)
    result = repo.constituents("881101.TI")
    assert [r["trend_rank"] for r in result["items"]] == [38, None]
    assert result["constituent_count"] == result["daily_valid_count"] == result["ma5_valid_count"] == 2
    assert result["ma20_valid_count"] == 0
    assert result["updated_at"] is not None
    assert repo.constituents("missing")["items"] == []
    assert repo.constituents("missing")["updated_at"] is None
    with db.bind.begin() as conn:
        m.op = Operations(MigrationContext.configure(conn))
        m.downgrade()
        assert Member.__tablename__ not in inspect(conn).get_table_names()


def test_trend_rank_query_uses_latest_cn_date_once_for_all_codes():
    from sqlalchemy import event
    from finance_analysis.database.models.trend_following import TrendFollowingSnapshot as Trend
    db = Database()
    Trend.__table__.create(db.bind)
    def trend(id, market, day, code, rank):
        return dict(id=id, market=market, trade_date=day, code=code, rank=rank, instrument_id=1,
                    universe_key="test", market_regime="NEUTRAL", market_score=50, trend_score=50,
                    rs_score=50, breakout_score=50, alpha_score=50, setup="NONE", state="IDLE",
                    reference_price=100, atr=1)
    with db.bind.begin() as conn:
        conn.execute(Trend.__table__.insert(), [
            trend(1, "CN", OLD, "600001.SH", 38),
            trend(2, "CN", date(2026, 9, 14), "600001.SH", 5),
            trend(3, "CN", date(2026, 9, 14), "600002.SH", 6),
            trend(4, "US", DAY, "600001.SH", 1),
            trend(5, "CN", OLD, "600003.SH", 20),
        ])
    queries = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)
    event.listen(db.bind, "before_cursor_execute", observe)
    repo = IndustryStrengthRepository(db)
    assert repo.latest_cn_trend_ranks(["600001.SH", "600001.SH", "600002.SH", "600003.SH", "MISSING"]) == {
        "600001.SH": 38, "600003.SH": 20,
    }
    assert len(queries) == 1
    # Latest date is across all CN rows, not only the requested codes.
    assert repo.latest_cn_trend_ranks(["600002.SH"]) == {}
    with db.bind.begin() as conn:
        conn.execute(Trend.__table__.delete().where(Trend.market == "CN"))
    assert repo.latest_cn_trend_ranks(["600001.SH"]) == {}


@pytest.fixture
def current_pg():
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("dedicated TEST_POSTGRES_URL required")
    admin = create_engine(url)
    schema = "test_industry_current_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            for m in (migration(), constituent_migration()):
                m.op = Operations(MigrationContext.configure(conn))
                m.upgrade()
        yield engine, IndustryStrengthRepository(Database(engine))
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def test_postgresql_generation_is_atomic_and_failure_rolls_back_snapshot_too(current_pg):
    from sqlalchemy import event
    engine, repo = current_pg
    repo.save(OLD, [payload(day=OLD)], constituents=[member(), member(industry="881102.TI")])
    old = repo.constituents("881101.TI")
    reads = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(("DELETE FROM industry_strength_constituent", "INSERT INTO industry_strength_constituent")):
            # Separate connection sees the entire previous committed generation at both write steps.
            reads.append(repo.constituents("881101.TI"))
            assert repo.constituents("881102.TI")["constituent_count"] == 1
            assert repo.ranking()[0]["trade_date"] == OLD
    event.listen(engine, "after_cursor_execute", observe)
    try:
        repo.save(DAY, [payload(rank=2)], constituents=[member("600002.SH", rank=None)])
    finally:
        event.remove(engine, "after_cursor_execute", observe)
    assert len(reads) == 2 and all(result == old for result in reads)
    latest = repo.constituents("881101.TI")
    assert latest["items"][0]["code"] == "600002.SH"
    assert latest["items"][0]["trend_rank"] is None
    assert repo.constituents("881102.TI")["items"] == []
    assert repo.ranking()[0]["strength_rank"] == 2

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO industry_strength_constituent"):
            raise RuntimeError("failed generation")
    event.listen(engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="failed generation"):
            repo.save(DAY, [payload(rank=3)], constituents=[member("600003.SH")])
    finally:
        event.remove(engine, "after_cursor_execute", fail)
    assert repo.constituents("881101.TI") == latest
    assert repo.ranking()[0]["strength_rank"] == 2
    repo.save(OLD, [payload(day=OLD, rank=4)])
    assert repo.constituents("881101.TI") == latest


def test_stock_context_uses_only_latest_official_date_and_current_membership():
    from finance_analysis.database.models.industry_strength import IndustryStrengthConstituent
    db = Database()
    Snapshot.__table__.create(db.bind)
    IndustryStrengthConstituent.__table__.create(db.bind)
    with db.session_scope() as session:
        session.add_all([Snapshot(**payload(day=OLD)), Snapshot(**payload(day=DAY)),
                         Snapshot(**payload(code="OLD_ONLY", day=OLD))])
        for industry in ["881101.TI", "OLD_ONLY"]:
            session.add(IndustryStrengthConstituent(industry_code=industry, stock_code="600001.SH", stock_name="Test"))
    rows = IndustryStrengthRepository(db).stock_context("600001.SH")
    assert len(rows) == 1
    assert rows[0]["trade_date"] == DAY
    assert rows[0]["industry_code"] == "881101.TI"
    assert rows[0]["members_observed_at"] is not None
    assert IndustryStrengthRepository(db).stock_context("AAPL.US") == []


def test_stock_context_api_is_read_only_and_cn_scoped(api):
    client, repo = api
    calls = []
    def read(code):
        calls.append(code)
        return [{"industry_code": "881101.TI", "industry_name": "Test", "trade_date": DAY,
                 "state": "STRONG", "strength_score": 80, "strength_rank": 1,
                 "members_observed_at": datetime(2026, 9, 16, tzinfo=timezone.utc)}]
    repo.stock_context = read
    response = client.get('/industry-strength/stocks/600001.SH/context')
    assert response.status_code == 200
    assert response.json()[0]["trade_date"] == DAY.isoformat()
    assert client.get('/industry-strength/stocks/AAPL.US/context').json() == []
    assert calls == ["600001.SH"]
    assert repo.calls == []

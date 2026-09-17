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


def _constituents_payload(code="881101.TI"):
    now = datetime.now(timezone.utc)
    return {
        "quality": {},
        "industry_code": code,
        "trade_date": DAY,
        "members_observed_at": now,
        "basis": "current_members_latest_completed_close",
        "constituent_count": 0,
        "daily_valid_count": 0,
        "ma5_valid_count": 0,
        "above_ma5_count": 0,
        "ma20_valid_count": 0,
        "above_ma20_count": 0,
        "up_count": 0,
        "down_count": 0,
        "flat_count": 0,
        "up_ratio": None,
        "above_ma5_ratio": None,
        "above_ma20_ratio": None,
        "equal_weight_return": None,
        "items": [],
    }


def _install_catalog(monkeypatch, codes=("881101.TI", "881199.TI")):
    catalog = [{"thscode": code, "name": code} for code in codes]

    class FakeMarket:
        def get_industry_catalog(self):
            return catalog

    def init(self, repository=None, market_data=None, config=None):
        self.repository = repository
        self.market_data = market_data or FakeMarket()
        self.config = config

    monkeypatch.setattr(endpoint.IndustryStrengthService, "__init__", init)


def test_api_constituents_accepts_catalog_industry_missing_from_ranking(api, monkeypatch):
    client, repo = api
    _install_catalog(monkeypatch)

    def ok(self, code):
        return _constituents_payload(code)

    monkeypatch.setattr(endpoint.IndustryStrengthService, "constituents", ok)
    response = client.get("/industry-strength/881199.TI/constituents")
    assert response.status_code == 200
    assert response.json()["industry_code"] == "881199.TI"
    assert repo.calls == []


def test_api_constituents_unknown_catalog_industry_is_404(api, monkeypatch):
    client, repo = api
    _install_catalog(monkeypatch)
    monkeypatch.setattr(
        endpoint.IndustryStrengthService,
        "constituents",
        lambda self, code: _constituents_payload(code),
    )
    response = client.get("/industry-strength/unknown/constituents")
    assert response.status_code == 404
    assert repo.calls == []


def test_api_constituents_current_only_and_sanitized_failure(api, monkeypatch):
    client, repo = api
    from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError

    _install_catalog(monkeypatch)

    def fail(*a):
        raise FuyaoError("private transport failure")

    monkeypatch.setattr(endpoint.IndustryStrengthService, "constituents", fail)
    response = client.get("/industry-strength/881101.TI/constituents")
    assert response.status_code == 503 and "private" not in response.text
    assert repo.calls == []
    assert client.get("/industry-strength/unknown/constituents").status_code == 404
    ranked_missing = client.get("/industry-strength/881199.TI/constituents")
    assert ranked_missing.status_code == 503 and "private" not in ranked_missing.text


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

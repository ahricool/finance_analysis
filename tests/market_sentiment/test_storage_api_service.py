import importlib.util
import os
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.market_sentiment import MarketSentimentSnapshot as Snapshot
from finance_analysis.database.models.market_sentiment import MarketSentimentSourceSnapshot as Source
from finance_analysis.database.repositories.market_sentiment import MarketSentimentRepository
from finance_analysis.integrations.market_data.models import MarketPoolSnapshot
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError
from finance_analysis.interfaces.api.deps import require_current_user, require_admin
from finance_analysis.interfaces.api.v1.endpoints import market_sentiment as endpoint
from finance_analysis.market_sentiment.calendar import sessions_through
from finance_analysis.market_sentiment.service import MarketSentimentService

DAY = date(2026, 9, 16)
PREV = date(2026, 9, 15)


class Database:
    def __init__(self, bind=None):
        self.bind = (
            bind
            if bind is not None
            else create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        )

    @contextmanager
    def get_session(self):
        with Session(self.bind) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.bind) as session, session.begin():
            yield session


def migrate(db, connection=None):
    spec = importlib.util.spec_from_file_location(
        "sentiment_migration", Path(__file__).parents[2] / "alembic/versions/0056_market_sentiment.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    with nullcontext(connection) if connection is not None else db.bind.begin() as connection:
        m.op = Operations(MigrationContext.configure(connection))
        m.upgrade()
        for model in (Snapshot, Source):
            assert {c["name"] for c in inspect(connection).get_columns(model.__tablename__)} == set(
                model.__table__.columns.keys()
            )
    return m


def source(day=DAY, count=1, board=1):
    rows = [
        dict(
            thscode=f"{i:06d}.SZ",
            name="测试",
            is_st=False,
            is_new=False,
            continue_day_cnt=board,
            continue_day_text="首板" if board == 1 else f"{board}连板",
            limit_up_time="09:50",
            seal_money=0,
            max_seal_money=10,
        )
        for i in range(count)
    ]
    now = datetime.now(timezone.utc)
    return MarketPoolSnapshot(day, "limit_up", now, now, count, rows, {"complete": True})


@pytest.fixture
def repo():
    db = Database()
    migrate(db)
    return MarketSentimentRepository(db)


def test_atomic_rerun_zero_and_failure_retains_success(repo, monkeypatch):
    repo.publish(DAY, {"limit_up": source()}, {})
    repo.publish(DAY, {"limit_up": source(count=0)}, {"limit_break": "FuyaoError"})
    assert repo.overview()["limit_up_count"] == 0
    assert repo.source(DAY, "limit_up")["total"] == 0
    with repo.db.get_session() as s:
        assert s.scalar(select(func.count()).select_from(Snapshot)) == 1
        assert s.scalar(select(func.count()).select_from(Source)) == 1
    with pytest.raises(ValueError):
        repo.publish(DAY, {"limit_up": replace(source(), quality={"complete": False})}, {})
    assert repo.overview()["limit_up_count"] == 0

    def fail(*a, **kw):
        raise RuntimeError("calculation failure")

    monkeypatch.setattr("finance_analysis.database.repositories.market_sentiment.calculate", fail)
    with pytest.raises(RuntimeError):
        repo.publish(DAY, {"limit_up": source()}, {})
    assert repo.overview()["limit_up_count"] == 0 and repo.source(DAY, "limit_up")["total"] == 0


def test_backfill_rebuilds_future_promotion_heat_and_state(repo):
    days = sessions_through(DAY, 22)
    for d in days[1:]:
        repo.publish(d, {"limit_up": source(d, board=2 if d == DAY else 1)}, {})
    assert repo.overview(days[-2])["heat_score"] is None
    repo.publish(days[0], {"limit_up": source(days[0])}, {})
    assert repo.overview(days[-2])["heat_score"] == 50
    repo.publish(PREV, {"limit_up": source(PREV, count=0)}, {})
    assert repo.overview(DAY)["promotions"]["1_to_2"]["denominator"] == 0
    repo.publish(PREV, {"limit_up": source(PREV)}, {})
    assert repo.overview(DAY)["promotions"]["1_to_2"]["ratio"] == 1
    assert repo.overview(DAY)["heat_score"] is not None


def test_service_core_failure_optional_failure_and_partial_retry(repo, monkeypatch):
    monkeypatch.setattr("finance_analysis.market_sentiment.service.expected_date", lambda: DAY)

    class Data:
        def get_limit_up_pool(self, d):
            if d == PREV:
                raise FuyaoError("unavailable")
            return source(d, count=0)

        def get_limit_down_pool(self, d):
            raise FuyaoError("down unavailable")

        def get_limit_break_pool(self, d):
            raise FuyaoError("break unavailable")

        def get_limit_up_ladder(self):
            raise FuyaoError("ladder unavailable")

    svc = MarketSentimentService(repo, Data())
    result = svc.run(backfill_days=2)
    assert result["status"] == "partial"
    assert [d["status"] for d in result["days"]] == ["failed", "completed"]
    assert repo.overview()["limit_up_count"] == 0
    assert set(repo.overview()["quality"]["optional_errors"]) == {"limit_down", "limit_break", "ladder"}
    with pytest.raises(ValueError):
        svc.run(backfill_days=32)
    with pytest.raises(ValueError):
        svc.run(date(2026, 9, 19))


def test_get_readonly_explicit_dates_pool_filters_and_auth(repo, monkeypatch):
    repo.publish(DAY, {"limit_up": source(count=0)}, {})
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.get_repository] = lambda: repo
    app.dependency_overrides[endpoint.get_industry_repository] = lambda: SimpleNamespace(ranking=lambda d, limit: [])
    with TestClient(app) as c:
        assert c.get("/dates").status_code == 401
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1, role="user")
    app.dependency_overrides[require_admin] = lambda: (_ for _ in ()).throw(__import__("fastapi").HTTPException(403))

    def no_io(*a, **kw):
        raise AssertionError("GET invoked network")

    monkeypatch.setattr("finance_analysis.integrations.market_data.service.MarketDataService.__init__", no_io)
    monkeypatch.setattr(endpoint, "expected_date", lambda: DAY)
    with TestClient(app) as c:
        assert c.get("/overview").json()["observation"]["limit_up_count"] == 0
        assert c.get("/overview?trade_date=2026-09-15").json()["observation"] is None
        assert c.get("/overview?trade_date=2026-09-15").json()["trade_date"] == str(PREV)
        assert c.get("/pool").json()["total"] == 0
        assert c.get("/pool?kind=limit_break").json()["total"] is None
        assert c.get("/pool?kind=limit_break").json()["available"] is False
        assert c.get("/pool?board=0").status_code == 422
        assert c.get("/history?days=2").json()["items"][0] is None
        assert c.get("/ladder").json()["source"] is None
        assert c.get("/dates").json() == [str(DAY)]
        assert c.post("/run", json={}).status_code == 403
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1)
        assert c.post("/run", json={"backfill_days": 32}).status_code == 422
        assert c.post("/run", json={"backfill_days": 2, "trade_date": str(DAY)}).status_code == 422
        from finance_analysis.tasks.celery.jobs.market_sentiment.tasks import run_market_sentiment_cn

        submitted = []
        monkeypatch.setattr(
            run_market_sentiment_cn, "apply_async", lambda **kw: submitted.append(kw) or SimpleNamespace(id="task-1")
        )
        assert c.post("/run", json={"trade_date": str(DAY)}).json()["task_id"] == "task-1"
        assert submitted[0]["queue"] == "analysis" and submitted[0]["kwargs"]["_triggered_by_uid"] == 1


def test_postgresql_atomic_publication():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("dedicated TEST_POSTGRES_URL required")
    engine = create_engine(url)
    schema = "sentiment_test_" + uuid4().hex
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
            conn.execute(text(f"SET LOCAL search_path TO {schema}"))
            # Use isolated schema metadata so this never migrates an application database.
            migrate(Database(conn), connection=conn)
            repo = MarketSentimentRepository(Database(conn))
            repo.publish(DAY, {"limit_up": source(count=0)}, {})
            repo.publish(DAY, {"limit_up": source(count=1)}, {})
            assert repo.overview()["limit_up_count"] == 1
            assert repo.source(DAY, "limit_up")["total"] == 1
        finally:
            transaction.rollback()
    engine.dispose()


def test_ladder_is_archived_by_actual_window_and_never_changes_full_pool(repo):
    now = datetime.now(timezone.utc)
    ladder = MarketPoolSnapshot(
        None,
        "ladder",
        now,
        now,
        1,
        [{"date": "20260916", "boards": {}}],
        {"complete": True},
        {"date_list": ["20260916"], "length": 1},
    )
    repo.publish(PREV, {"limit_up": source(PREV, count=7, board=3), "ladder": ladder}, {})
    assert repo.overview(PREV)["multi_board_count"] == 7
    assert repo.ladder(PREV) is None
    assert repo.ladder(DAY)["trade_date"] == DAY
    assert repo.ladder(DAY)["requested_trade_date"] is None


def test_new_optional_failure_removes_old_generation(repo):
    supplement = replace(source(), source_kind="limit_break")
    repo.publish(DAY, {"limit_up": source(), "limit_break": supplement}, {})
    assert repo.source(DAY, "limit_break")["total"] == 1
    repo.publish(DAY, {"limit_up": source(count=0)}, {"limit_break": "FuyaoError"})
    assert repo.source(DAY, "limit_break") is None
    assert "limit_break" not in repo.overview()["supplements"]


def test_migration_downgrade():
    db = Database()
    migration = migrate(db)
    with db.bind.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()
        assert not set(inspect(conn).get_table_names()) & {Source.__tablename__, Snapshot.__tablename__}

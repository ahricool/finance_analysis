"""Atomic private snapshots, daily deduplication, history reads and migrations."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime
from types import SimpleNamespace as NS
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.database.models.user import User
from finance_analysis.database.models.notification import Notification
from finance_analysis.database.models.portfolio import PortfolioAccount
from finance_analysis.database.models.holdings_review import HoldingsReview
from finance_analysis.database.repositories.holdings_review import HoldingsReviewRepository
from finance_analysis.holdings_review.service import HoldingsReviewService
from finance_analysis.holdings_review.decision import fallback
from finance_analysis.interfaces.api.v1.endpoints import holdings_review as endpoint

DAY = date(2026, 10, 30)
NOW = datetime.fromisoformat("2026-10-30T14:10:00+08:00")


@compiles(JSONB, "sqlite")
def jsonb_sqlite(type_, compiler, **kwargs):
    return "JSON"


class Database:
    def __init__(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        for model in (User, Notification, PortfolioAccount, HoldingsReview):
            model.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session, session.begin():
            yield session


@pytest.fixture
def repo():
    db = Database()
    with db.session_scope() as session:
        for uid in (7, 8):
            session.add(User(id=uid, username=str(uid), email=f"{uid}@example.com", role="user", extra={}))
            session.add(PortfolioAccount(uid=uid, market="CN", name=str(uid), cash=10000))
    yield HoldingsReviewRepository(db)
    db.engine.dispose()


def snapshot():
    return {
        "market": "CN",
        "trade_date": str(DAY),
        "as_of": NOW.isoformat(),
        "session_close": NOW.replace(hour=15).isoformat(),
        "holdings": [],
        "portfolio": {},
        "data_quality": [],
        "research": {},
        "indices": [],
    }


class Lock:
    acquired = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_daily_service_commits_review_and_notification_only_once_and_isolates_users(repo):
    context = snapshot()
    calls, pushed = [], []
    maker = NS(decide=lambda uid, ctx: (calls.append(uid) or fallback(ctx, "test"), {"status": "unavailable"}, {}))
    service = HoldingsReviewService(
        repository=repo,
        builder=NS(build=lambda *args: deepcopy(context)),
        maker=maker,
        lock_factory=lambda *a: Lock(),
        push=lambda *a: pushed.append(a),
    )
    assert service.run("CN", uid=7, now=NOW)["completed"] == 1
    assert service.run("CN", uid=7, now=NOW)["already_completed"] == 1
    assert calls == [7] and len(pushed) == 1
    assert repo.get(8, "CN", DAY) is None
    saved = repo.get(7, "CN", DAY)
    assert saved["status"] == "completed" and saved["markdown"].startswith("# A股持仓复盘")
    context["portfolio"]["cash"] = 999  # Frozen input is independent of later changes.
    assert saved["portfolio"] == {}
    with repo.db.get_session() as session:
        messages = session.scalars(select(Notification)).all()
        assert len(messages) == 1 and messages[0].uid == 7 and messages[0].content == saved["markdown"]


def test_push_failure_keeps_committed_result_and_processing_failure_is_visible(repo):
    def fail_push(*args):
        raise RuntimeError("delivery unavailable")

    service = HoldingsReviewService(
        repository=repo,
        builder=NS(build=lambda *a: snapshot()),
        maker=NS(decide=lambda uid, ctx: (fallback(ctx, "test"), {}, {})),
        lock_factory=lambda *a: Lock(),
        push=fail_push,
    )
    assert service.run("CN", uid=7, now=NOW)["completed"] == 1

    def fail_builder(*args):
        raise RuntimeError("failure")

    service.builder = NS(build=fail_builder)
    assert service.run("CN", uid=8, now=NOW)["failed"] == 1
    assert repo.get(7, "CN", DAY)["status"] == "completed"
    assert repo.get(8, "CN", DAY)["status"] == "failed"
    with repo.db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(Notification)) == 1


def test_get_is_read_only_defaults_to_previous_session_and_never_reads_another_user(repo, monkeypatch):
    prior = date(2026, 10, 29)
    repo.start(7, "CN", prior, snapshot())
    repo.complete(7, "CN", prior, fallback(snapshot(), "test"), "private report", {})
    repo.start(8, "CN", DAY, snapshot())
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/reviews")
    app.dependency_overrides[endpoint.require_current_user] = lambda: None
    app.dependency_overrides[endpoint.repository] = lambda: repo
    monkeypatch.setattr(endpoint, "get_effective_uid", lambda request: 7)
    monkeypatch.setattr(endpoint, "default_dates", lambda market: (DAY, prior))
    monkeypatch.setattr(endpoint, "review_window", lambda market: None)
    with TestClient(app) as http:
        result = http.get("/reviews?market=CN&uid=8")
        assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
        assert result.json()["review"]["trade_date"] == str(prior)
        assert http.get(f"/reviews?market=CN&trade_date={DAY}").json()["review"] is None
        assert len(http.get("/reviews/dates?market=CN").json()["items"]) == 1
        assert http.post("/reviews/run?market=CN").status_code == 409
        assert http.get("/reviews?market=HK").status_code == 422


def test_migration_matches_current_model_and_rolls_back():
    path = Path(__file__).parents[2] / "alembic/versions/0088_holdings_review.py"
    spec = importlib.util.spec_from_file_location("holdings_review_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine("sqlite://").begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        assert {c["name"] for c in inspect(conn).get_columns("holdings_review")} == set(
            HoldingsReview.__table__.columns.keys()
        )
        assert inspect(conn).get_unique_constraints("holdings_review")[0]["column_names"] == [
            "uid",
            "market",
            "trade_date",
        ]
        migration.downgrade()
        assert "holdings_review" not in inspect(conn).get_table_names()

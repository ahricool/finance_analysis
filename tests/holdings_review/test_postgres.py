"""Opt-in PostgreSQL migration, private persistence and advisory-lock regression."""

import importlib.util
import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text, inspect, select
from sqlalchemy.orm import Session

from finance_analysis.database.models.user import User
from finance_analysis.database.models.notification import Notification
from finance_analysis.database.models.portfolio import PortfolioAccount
from finance_analysis.database.models.holdings_review import HoldingsReview
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.research_preview import ResearchPreview, ResearchPreviewItem
from finance_analysis.database.repositories.holdings_review import HoldingsReviewRepository
from finance_analysis.database.repositories.research_preview import PreviewRepository
from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock


@pytest.mark.skipif(
    not os.getenv("HOLDINGS_REVIEW_TEST_DATABASE_URL"), reason="Requires an isolated PostgreSQL database"
)
def test_real_migration_private_completion_preview_bounds_and_lock_release():
    engine = create_engine(os.environ["HOLDINGS_REVIEW_TEST_DATABASE_URL"])
    schema = "holdings_review_" + uuid4().hex
    scoped = engine.execution_options(schema_translate_map={None: schema})
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    class DB:
        @contextmanager
        def get_session(self):
            with Session(scoped) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with self.get_session() as session, session.begin():
                yield session

        def connect(self):
            return engine.connect()

    try:
        for model in (User, Notification, PortfolioAccount, Instrument, ResearchPreview, ResearchPreviewItem):
            model.__table__.create(scoped)
        spec = importlib.util.spec_from_file_location(
            "review_migration", Path(__file__).parents[2] / "alembic/versions/0088_holdings_review.py"
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            assert {c["name"] for c in inspect(conn).get_columns("holdings_review")} == set(
                HoldingsReview.__table__.columns.keys()
            )
        db = DB()
        with db.session_scope() as session:
            session.add(User(id=7, username="seven", email="seven@example.com", role="user", extra={}))
            session.add(PortfolioAccount(uid=7, name="CN", market="CN", cash=100))
        repo = HoldingsReviewRepository(db)
        assert repo.user_ids("CN") == [7]
        day = date(2026, 10, 30)
        repo.start(7, "CN", day, {"holdings": []})
        notification_id = repo.complete(7, "CN", day, {"risks": []}, "# Frozen", {"status": "unverified"})
        assert notification_id and repo.get(7, "CN", day)["markdown"] == "# Frozen"
        assert repo.get(8, "CN", day) is None
        assert repo.complete(7, "CN", day, {"risks": []}, "overwrite", {}) is None
        with db.get_session() as session:
            assert session.scalar(select(Notification.uid)) == 7
        preview = PreviewRepository(db)
        now = datetime(2026, 10, 30, 6, tzinfo=timezone.utc)
        preview.publish(
            "trend_following",
            "CN",
            20,
            {"trade_date": str(day)},
            [{"kind": "stock", "item_key": str(i), "summary": {"code": str(i), "state": "WATCHING"}} for i in range(5)],
            observed_at=now,
            expires_at=now.replace(hour=8),
        )
        result = preview.read("trend_following", "CN", 20, item_keys=["2"], view="summary", now=now)
        assert [r["item_key"] for r in result["items"]] == ["2"]
        assert len(preview.read("trend_following", "CN", 20, limit=2, now=now)["items"]) == 2
        assert not preview.read("trend_following", "CN", 20, item_keys=[], now=now)["items"]
        first = PostgreSQLAdvisoryLock(7, db_manager=db, namespace=20_261_101)
        second = PostgreSQLAdvisoryLock(7, db_manager=db, namespace=20_261_101)
        assert first.acquire() and not second.acquire()
        first.release()
        assert second.acquire()
        second.release()
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()

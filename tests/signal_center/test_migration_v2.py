"""Additive migration retains V1 history; completion atomically stores one global message."""

from contextlib import contextmanager
from datetime import date
import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from finance_analysis.database.models.signal_center import SignalCenterRun
from finance_analysis.database.models.notification import Notification
from finance_analysis.database.repositories.signal_center import SignalCenterRepository
from finance_analysis.database.base import Base


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[2] / f"alembic/versions/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_migration_preserves_legacy_and_matches_model():
    engine = create_engine("sqlite://")
    old, new = load("0067_signal_center"), load("0080_signal_center_v2")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        Notification.__table__.create(conn)
        old.op = new.op = Operations(MigrationContext.configure(conn))
        old.upgrade()
        # Use reflected legacy schema so new columns are not accidentally referenced before the migration.
        from sqlalchemy import MetaData, Table

        table = Table("signal_center_run", MetaData(), autoload_with=conn)
        from finance_analysis.core.time import utc_now

        conn.execute(
            table.insert().values(
                market="CN",
                signal_date=date(2026, 9, 22),
                status="completed",
                decision="NO_TRADE",
                confidence="low",
                analysis={"thesis": "历史结论"},
                candidate_snapshot={},
                prompt_version="v1",
                system_prompt="s",
                prompt="p",
                created_at=utc_now(),
            )
        )
        new.upgrade()
        assert {c["name"] for c in inspect(conn).get_columns("signal_center_run")} == set(
            SignalCenterRun.__table__.c.keys()
        )
        row = conn.execute(select(SignalCenterRun.__table__)).mappings().one()
        assert row["recommendations"] is None and row["analysis"] == {"thesis": "历史结论"}
        new.downgrade()
        assert {c["name"] for c in inspect(conn).get_columns("signal_center_run")} == set(table.c.keys())


def test_atomic_completion_is_idempotent_and_rolls_back_message_on_failure():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Notification.__table__, SignalCenterRun.__table__])

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

    repo = SignalCenterRepository(DB())
    day = date(2026, 9, 22)
    fields = dict(status="pending", candidate_snapshot={}, prompt_version="v2", system_prompt="s", prompt="p")
    repo.create("CN", day, **fields)
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        repo.complete("CN", day, notification_content="must roll back", decision="BUY", confidence="high", analysis={})
    with Session(engine) as session:
        assert list(session.scalars(select(Notification))) == []
    assert repo.get("CN", day)["status"] == "pending"
    with pytest.raises(ValueError, match="frozen"):
        repo.complete("CN", day, notification_content="cannot change input", candidate_snapshot={"changed": True})
    notification_id = repo.complete(
        "CN",
        day,
        notification_content="结论与证据",
        decision="NO_TRADE",
        recommendations=[],
        confidence="low",
        analysis={"thesis": "无优势"},
    )
    assert notification_id and repo.get("CN", day)["notification_id"] == notification_id
    assert repo.complete("CN", day, notification_content="duplicate") is None
    with Session(engine) as session:
        row = session.scalars(select(Notification)).one()
        assert row.uid is None and row.content == "结论与证据" and row.route_type == "report"

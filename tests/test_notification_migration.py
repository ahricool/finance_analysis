"""Execute message cleanup on old schema without losing calendar domain events."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from finance_analysis.database.models import Notification


def exercise(connection, monkeypatch):
    connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
    connection.execute(sa.text("CREATE TABLE timeline_entries (id INTEGER PRIMARY KEY, content TEXT)"))
    connection.execute(sa.text("INSERT INTO timeline_entries VALUES (1, 'old report'), (2, 'old premarket')"))
    connection.execute(
        sa.text(
            "CREATE TABLE finance_events (id INTEGER PRIMARY KEY, calendar_type VARCHAR(32), "
            "title TEXT, notified_at TIMESTAMP, notification_fingerprint VARCHAR(96))"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO finance_events (id, calendar_type, title) VALUES "
            "(1, 'earnings', 'NVDA earnings'), (2, 'macro', 'CPI')"
        )
    )
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0049_notification_center.py"
    spec = importlib.util.spec_from_file_location("notification_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    module.upgrade()
    inspector = sa.inspect(connection)
    assert {c["name"] for c in inspector.get_columns("notification")} == set(Notification.__table__.columns.keys())
    assert len(inspector.get_indexes("notification")) == 4
    assert connection.scalar(sa.text("SELECT count(*) FROM timeline_entries")) == 0
    assert connection.scalar(sa.text("SELECT count(*) FROM notification")) == 0
    assert connection.execute(sa.text("SELECT calendar_type, title FROM finance_events ORDER BY id")).all() == [
        ("earnings", "NVDA earnings"),
        ("macro", "CPI"),
    ]
    assert {c["name"] for c in inspector.get_columns("finance_events")} == {"id", "calendar_type", "title"}
    with pytest.raises(RuntimeError, match="irreversible"):
        module.downgrade()


def test_cleanup_sqlite(monkeypatch):
    with sa.create_engine("sqlite://").begin() as connection:
        exercise(connection, monkeypatch)


def test_cleanup_postgresql(monkeypatch):
    url = os.getenv("NOTIFICATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("NOTIFICATION_TEST_DATABASE_URL must point to an isolated test database")
    engine = sa.create_engine(url)
    schema = "notification_test_" + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            exercise(connection, monkeypatch)
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()


def test_single_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0049_notification_center"]

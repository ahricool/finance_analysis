"""Usage persistence and destructive schema migration on isolated test data."""

import importlib.util
import os
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.core.time import utc_now
from finance_analysis.database.models import LLMUsage
from finance_analysis.database.repositories.llm_usage import LLMUsageMixin


class Store(LLMUsageMixin):
    def __init__(self):
        self.engine = sa.create_engine("sqlite://")
        LLMUsage.__table__.create(self.engine)

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session, session.begin():
            yield session


def test_usage_keeps_failed_attempts_and_uid_scope():
    store = Store()
    store.record_llm_usage(
        uid=1,
        call_type="analysis",
        backend="api",
        engine=None,
        model="test",
        status="success",
        input_tokens=2,
        output_tokens=3,
        total_tokens=5,
    )
    store.record_llm_usage(
        uid=2,
        call_type="generic",
        backend="cli",
        engine="agy",
        model=None,
        status="failed",
        error="x" * 900,
    )
    now = utc_now()
    scoped = store.get_llm_usage_summary(now - timedelta(days=1), now, uid=1)
    assert scoped["total_calls"] == 1 and scoped["total_tokens"] == 5
    scoped = store.get_llm_usage_summary(now - timedelta(days=1), now, uid=2)
    assert scoped["total_calls"] == 1 and scoped["total_tokens"] == 0
    assert scoped["by_model"][0]["model"] == "unknown"
    with store.session_scope() as session:
        row = session.scalars(sa.select(LLMUsage).where(LLMUsage.uid == 2)).one()
        assert row.backend == "cli" and row.engine == "agy" and len(row.error) == 500
    store.engine.dispose()


def test_migration_postgresql(monkeypatch):
    url = os.getenv("LLM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("LLM_TEST_DATABASE_URL must point to an isolated test database")
    engine = sa.create_engine(url)
    schema = "llm_test_" + uuid4().hex
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0052_simplify_llm.py"
    spec = importlib.util.spec_from_file_location("llm_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(sa.text("CREATE TABLE conversation_messages (id INTEGER PRIMARY KEY, content TEXT)"))
            connection.execute(sa.text("INSERT INTO conversation_messages VALUES (1, 'old chat')"))
            connection.execute(
                sa.text("""CREATE TABLE llm_usage (
                id SERIAL PRIMARY KEY, uid INTEGER, call_type VARCHAR(32) NOT NULL, model VARCHAR(128) NOT NULL,
                stock_code VARCHAR(16), prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL, called_at TIMESTAMPTZ)""")
            )
            connection.execute(
                sa.text(
                    "INSERT INTO llm_usage (call_type, model, stock_code, prompt_tokens, completion_tokens, total_tokens) VALUES ('analysis', 'm', 'TEST', 2, 3, 5)"
                )
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert not sa.inspect(connection).has_table("conversation_messages", schema=schema)
            assert {c["name"] for c in sa.inspect(connection).get_columns("llm_usage", schema=schema)} == set(
                LLMUsage.__table__.columns.keys()
            )
            row = connection.execute(
                sa.text("SELECT backend, status, input_tokens, output_tokens, total_tokens FROM llm_usage")
            ).one()
            assert tuple(row) == ("api", "success", 2, 3, 5)
            migration.downgrade()
            assert connection.scalar(sa.text("SELECT count(*) FROM conversation_messages")) == 0
            assert connection.scalar(sa.text("SELECT total_tokens FROM llm_usage")) == 5
            migration.upgrade()
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()


def test_removed_api_and_request_surface():
    from finance_analysis.interfaces.api.v1.router import router
    from finance_analysis.llm import LLMRequest
    from finance_analysis.database import DatabaseManager

    assert not any(route.path.startswith("/api/v1/agent") for route in router.routes)
    assert set(LLMRequest.__dataclass_fields__) == {
        "prompt",
        "system_prompt",
        "temperature",
        "max_tokens",
        "timeout",
        "call_type",
        "uid",
    }
    assert not hasattr(DatabaseManager, "save_conversation_message")

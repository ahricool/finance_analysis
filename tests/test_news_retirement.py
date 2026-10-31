"""News retirement removes its history while retaining macro and earnings research."""

import importlib.util
import io
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.core.paths import clear_paths_cache
from finance_analysis.database.base import Base


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0086_retire_news.py"
    spec = importlib.util.spec_from_file_location("retire_news", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=("sqlite", "postgresql"))
def connection(request):
    url = "sqlite://" if request.param == "sqlite" else os.getenv("STOCK_RETIREMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("STOCK_RETIREMENT_TEST_DATABASE_URL must point to an isolated test database")
    engine = sa.create_engine(url)
    schema = "retire_news_" + uuid4().hex
    try:
        with engine.begin() as conn:
            if request.param == "postgresql":
                conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
                conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            yield conn
            if request.param == "postgresql":
                conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()


def test_no_news_task_storage_or_adapter_remains():
    from finance_analysis.tasks.celery.app import celery_app
    from finance_analysis.tasks.celery.schedule import build_beat_schedule, get_scheduled_task_definition
    from finance_analysis.database import models

    celery_app.loader.import_default_modules()
    assert get_scheduled_task_definition("analysis_us_premarket_news") is None
    assert "scheduled.analysis_us_premarket_news" not in celery_app.tasks
    assert not any(item["task"] == "scheduled.analysis_us_premarket_news" for item in build_beat_schedule().values())
    assert not {"news_intel", "news_intel_usage", "news_analysis"}.intersection(Base.metadata.tables)
    assert not any(hasattr(models, name) for name in ("NewsIntel", "NewsIntelUsage", "NewsAnalysis"))
    root = Path(__file__).resolve().parents[1] / "src/finance_analysis"
    assert not list((root / "tasks/celery/jobs/us_premarket_news").glob("*.py"))
    assert not (root / "integrations/market_data/providers/longbridge/news.py").exists()
    for name in ("scheduled.market_calendar", "scheduled.earnings_outlook_final", "scheduled.earnings_outlook_review"):
        assert name in celery_app.tasks


@pytest.mark.parametrize("custom_audit", (False, True))
def test_history_and_files_are_purged_without_touching_finance_events(connection, monkeypatch, tmp_path, custom_audit):
    module = migration()
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    clear_paths_cache()
    root = tmp_path / "data/logs"
    (root / "celery").mkdir(parents=True)
    old_log = root / "celery/美股盘前新闻情报_old.log"
    old_log.write_text("news")
    kept_log = root / "celery/财报前瞻_keep.log"
    kept_log.write_text("earnings")
    outside = tmp_path / "outside.log"
    outside.write_text("keep")
    audit = tmp_path / "audit" if custom_audit else root / "llm"
    if custom_audit:
        monkeypatch.setenv("LLM_LOG_DIR", str(audit))
    else:
        monkeypatch.delenv("LLM_LOG_DIR", raising=False)
    audit.mkdir()
    kept = b'{"call_type":"earnings_outlook","prompt":"keep"}\ninvalid line\n'
    audit_file = audit / "test.log"
    audit_file.write_bytes(
        b'{"call_type":"us_premarket_news_importance"}\n' + b'{"call_type":"us_premarket_news_impact"}\n' + kept
    )
    metadata = sa.MetaData()
    tasks = sa.Table(
        "task",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_type", sa.String),
        sa.Column("scheduler_job_id", sa.String),
        sa.Column("task_log", sa.String),
        sa.Column("result", sa.Text),
    )
    messages = sa.Table(
        "notification",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String),
        sa.Column("route_type", sa.String),
        sa.Column("content", sa.Text),
    )
    usage = sa.Table(
        "llm_usage", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("call_type", sa.String)
    )
    finance = sa.Table(
        "finance_events", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("calendar_type", sa.String)
    )
    outlook = sa.Table("earnings_outlook_state", metadata, sa.Column("id", sa.Integer, primary_key=True))
    facts = sa.Table("news_intel", metadata, sa.Column("id", sa.Integer, primary_key=True))
    for name in ("news_intel_usage", "news_analysis"):
        sa.Table(
            name,
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("news_intel_id", sa.Integer, sa.ForeignKey(facts.c.id)),
        )
    metadata.create_all(connection)
    connection.execute(
        tasks.insert(),
        [
            dict(
                id=1,
                task_type=module.TASK_TYPE,
                scheduler_job_id=None,
                task_log=str(old_log),
                result=json.dumps({"notification_id": 7}),
            ),
            dict(
                id=2, task_type="legacy", scheduler_job_id=module.JOB_ID, task_log="../../outside.log", result="broken"
            ),
            dict(
                id=3,
                task_type="scheduled_earnings_outlook_final",
                scheduler_job_id=None,
                task_log=str(kept_log),
                result="keep",
            ),
        ],
    )
    connection.execute(
        messages.insert(),
        [
            dict(id=1, title="美股盘前新闻情报", route_type="report", content="news"),
            dict(id=2, title="美股收盘复盘", route_type="report", content="keep"),
            dict(id=3, title="error", route_type="system_error", content=f"\n- 类型：{module.TASK_TYPE}\nnews"),
            dict(
                id=4,
                title="error",
                route_type="system_error",
                content="\n- 类型：scheduled_earnings_outlook_final\nkeep",
            ),
            dict(id=7, title="renamed report", route_type="report", content="owned by old task"),
        ],
    )
    connection.execute(
        usage.insert(),
        [
            dict(id=i, call_type=kind)
            for i, kind in enumerate(
                (*module.CALL_TYPES, "earnings_outlook", "market_calendar_importance", "signal_center"), 1
            )
        ],
    )
    connection.execute(finance.insert(), [dict(id=1, calendar_type="macro"), dict(id=2, calendar_type="earnings")])
    connection.execute(outlook.insert().values(id=1))
    connection.execute(facts.insert().values(id=1))
    for name in ("news_intel_usage", "news_analysis"):
        connection.execute(metadata.tables[name].insert().values(id=1, news_intel_id=1))
    try:
        module.upgrade()
        module.upgrade()
        assert not {"news_intel", "news_intel_usage", "news_analysis"}.intersection(
            sa.inspect(connection).get_table_names()
        )
        assert connection.scalars(sa.select(tasks.c.id)).all() == [3]
        assert connection.scalars(sa.select(messages.c.id).order_by(messages.c.id)).all() == [2, 4]
        assert set(connection.scalars(sa.select(usage.c.call_type))) == {
            "earnings_outlook",
            "market_calendar_importance",
            "signal_center",
        }
        assert set(connection.scalars(sa.select(finance.c.calendar_type))) == {"earnings", "macro"}
        assert connection.scalar(sa.select(sa.func.count()).select_from(outlook)) == 1
        assert not old_log.exists()
        assert kept_log.read_text() == "earnings"
        assert outside.read_text() == "keep"
        assert audit_file.read_bytes() == kept
        with pytest.raises(RuntimeError, match="irreversible"):
            module.downgrade()
    finally:
        clear_paths_cache()


def test_empty_or_partially_removed_schema_is_safe(connection, monkeypatch, tmp_path):
    module = migration()
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    clear_paths_cache()
    try:
        module.upgrade()
        connection.execute(sa.text("CREATE TABLE news_intel (id INTEGER PRIMARY KEY)"))
        module.upgrade()
        assert "news_intel" not in sa.inspect(connection).get_table_names()
    finally:
        clear_paths_cache()


def test_audit_cleanup_honors_home_relative_llm_log_dir(monkeypatch, tmp_path):
    from tempfile import TemporaryDirectory

    module = migration()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    clear_paths_cache()
    try:
        with TemporaryDirectory(prefix="fa-news-audit-", dir=Path.home()) as folder:
            audit_dir = Path(folder)
            monkeypatch.setenv("LLM_LOG_DIR", f"~/{audit_dir.name}")
            audit_file = audit_dir / "attempts.log"
            kept = b'{"call_type":"earnings_outlook","prompt":"keep"}\n'
            audit_file.write_bytes(b'{"call_type":"us_premarket_news_importance"}\n' + kept)
            module._purge_files([])
            assert audit_file.read_bytes() == kept
    finally:
        clear_paths_cache()


def test_offline_sql_emits_cleanup_and_no_calendar_deletion():
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    module = migration()
    module.op = Operations(context)
    module.upgrade()
    sql = output.getvalue()
    assert "DROP TABLE IF EXISTS news_intel" in sql
    assert "DELETE FROM task" in sql
    assert "pg_input_is_valid" in sql
    assert "DELETE FROM finance_events" not in sql
    assert "DELETE FROM earnings_outlook" not in sql


def test_options_explanation_keeps_calendar_context_without_news_tables():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from sqlalchemy.orm import Session

    from finance_analysis.database.models.market_calendar import FinanceEvent
    from finance_analysis.database.repositories.options_intelligence import OptionsRepository

    now = datetime(2026, 10, 7, 22, tzinfo=timezone.utc)
    engine = sa.create_engine("sqlite://")
    FinanceEvent.__table__.create(engine)
    try:
        with Session(engine) as session, session.begin():
            for kind in ("earnings", "macro"):
                session.add(
                    FinanceEvent(
                        provider="test",
                        event_key=kind,
                        calendar_type=kind,
                        market="US",
                        symbol="AAPL.US" if kind == "earnings" else None,
                        event_date=now.date(),
                        title=kind,
                        content=kind,
                        first_seen_at=now - timedelta(days=1),
                    )
                )
            session.add(
                FinanceEvent(
                    provider="test",
                    event_key="future_knowledge",
                    calendar_type="earnings",
                    market="US",
                    symbol="AAPL.US",
                    event_date=now.date(),
                    title="not yet known",
                    content="not yet known",
                    first_seen_at=now + timedelta(days=1),
                )
            )
        repo = OptionsRepository(SimpleNamespace(get_session=lambda: Session(engine)))
        context = repo.context("AAPL.US", now)
        assert set(context) == {"calendar"}
        assert {item["type"] for item in context["calendar"]} == {"earnings"}
        assert {item["title"] for item in context["calendar"]} == {"earnings"}
        with Session(engine) as session:
            assert (
                session.scalar(
                    sa.select(sa.func.count()).select_from(FinanceEvent).where(FinanceEvent.calendar_type == "macro")
                )
                == 1
            )
    finally:
        engine.dispose()

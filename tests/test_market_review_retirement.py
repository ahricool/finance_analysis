"""Delete only the retired manual recap, including its private report history."""

import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.core.paths import clear_paths_cache


@pytest.fixture(params=("sqlite", "postgresql"))
def connection(request):
    if request.param == "postgresql":
        url = os.getenv("STOCK_RETIREMENT_TEST_DATABASE_URL")
        if not url:
            pytest.skip("STOCK_RETIREMENT_TEST_DATABASE_URL must point to an isolated database")
    else:
        url = "sqlite://"
    engine = sa.create_engine(url)
    schema = "manual_review_" + uuid4().hex
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


@pytest.mark.parametrize("custom_audit", (False, True))
def test_old_recap_history_is_purged_without_touching_scheduled_us_review(
    connection, monkeypatch, tmp_path, custom_audit
):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0085_retire_market_review.py"
    spec = importlib.util.spec_from_file_location("retire_manual_review", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    clear_paths_cache()
    log_root = tmp_path / "data/logs"
    (log_root / "celery").mkdir(parents=True)
    old_log = log_root / "celery/大盘复盘_old.log"
    new_log = log_root / "celery/美股收盘复盘_new.log"
    old_log.write_text("old report")
    new_log.write_text("keep US review")
    outside = tmp_path / "outside.log"
    outside.write_text("keep outside log root")
    audit = tmp_path / "custom-audit" if custom_audit else log_root / "llm"
    if custom_audit:
        monkeypatch.setenv("LLM_LOG_DIR", str(audit))
    else:
        monkeypatch.delenv("LLM_LOG_DIR", raising=False)
    audit.mkdir()
    retained = b'{"call_type":"us_postmarket_review","prompt":"keep"}\n'
    audit_file = audit / "2026-10-31.log"
    audit_file.write_bytes(b'{"call_type":"market_review","prompt":"delete"}\n' + retained + b"invalid old line\n")
    metadata = sa.MetaData()
    tasks = sa.Table(
        "task",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_type", sa.String),
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
    metadata.create_all(connection)
    connection.execute(
        tasks.insert(),
        [
            dict(
                id=1,
                task_type="market_review",
                task_log="celery/大盘复盘_old.log",
                result=json.dumps({"notification_id": 7}),
            ),
            dict(id=2, task_type="market_review", task_log="../../outside.log", result="broken json"),
            dict(id=3, task_type="scheduled_us_postmarket_review", task_log=str(new_log), result="keep"),
        ],
    )
    connection.execute(
        messages.insert(),
        [
            dict(id=1, title="🎯 大盘复盘", route_type="report", content="old"),
            dict(id=2, title="美股收盘复盘", route_type="report", content="keep"),
            dict(id=3, title="🎯 Market Review", route_type="report", content="old English"),
            dict(id=4, title="任务失败通知", route_type="system_error", content="\n- 类型：market_review\nold error"),
            dict(
                id=5,
                title="任务失败通知",
                route_type="system_error",
                content="\n- 类型：scheduled_us_postmarket_review\nkeep",
            ),
            dict(id=6, title="🎯 大盘复盘", route_type="alert", content="keep unrelated route"),
            dict(id=7, title="Legacy renamed report", route_type="report", content="linked old output"),
        ],
    )
    connection.execute(
        usage.insert(), [dict(id=1, call_type="market_review"), dict(id=2, call_type="us_postmarket_review")]
    )
    try:
        migration.upgrade()
        migration.upgrade()
        assert connection.scalars(sa.select(tasks.c.id)).all() == [3]
        assert connection.scalars(sa.select(messages.c.id).order_by(messages.c.id)).all() == [2, 5, 6]
        assert connection.scalars(sa.select(usage.c.id)).all() == [2]
        assert not old_log.exists()
        assert new_log.read_text() == "keep US review"
        assert outside.read_text() == "keep outside log root"
        assert audit_file.read_bytes() == retained + b"invalid old line\n"
        with pytest.raises(RuntimeError, match="irreversible"):
            migration.downgrade()
    finally:
        clear_paths_cache()


def test_retired_manual_and_scheduled_reviews_are_not_registered():
    from finance_analysis.tasks.celery.app import celery_app

    celery_app.loader.import_default_modules()
    assert "analysis.run_market_review" not in celery_app.tasks
    assert "scheduled.analysis_us_postmarket_review" not in celery_app.tasks
    assert "scheduled.analysis_us_pre_close_review" in celery_app.tasks

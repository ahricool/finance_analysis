"""Retire only the standalone report; retain real holdings and shared market inputs."""

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


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0089_retire_us_postmarket.py"
    spec = importlib.util.spec_from_file_location("retire_us_postmarket", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=("sqlite", "postgresql"))
def connection(request):
    url = "sqlite://" if request.param == "sqlite" else os.getenv("STOCK_RETIREMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("STOCK_RETIREMENT_TEST_DATABASE_URL must point to an isolated test database")
    engine = sa.create_engine(url)
    schema = "retire_postmarket_" + uuid4().hex
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


def history_tables(connection):
    meta = sa.MetaData()
    task = sa.Table(
        "task", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("task_type", sa.String),
        sa.Column("scheduler_job_id", sa.String), sa.Column("task_log", sa.String), sa.Column("result", sa.Text),
    )
    notification = sa.Table(
        "notification", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("title", sa.String),
        sa.Column("route_type", sa.String), sa.Column("content", sa.Text),
    )
    usage = sa.Table(
        "llm_usage", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("call_type", sa.String),
    )
    timeline = sa.Table(
        "timeline_entries", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("entry_type", sa.String),
    )
    universe = sa.Table("universe", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("key", sa.String))
    members = sa.Table(
        "universe_member", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("universe_id", sa.Integer),
        sa.Column("source", sa.String),
    )
    # Sentinels: these shared facts must never be deleted by report retirement.
    for name in ("stock_daily", "instrument", "portfolio_position", "holdings_review", "finance_events"):
        table = sa.Table(name, meta, sa.Column("id", sa.Integer, primary_key=True))
        table.create(connection)
        connection.execute(table.insert().values(id=1))
    meta.create_all(connection)
    connection.execute(task.insert(), [
        dict(id=1, task_type="scheduled_us_postmarket_review", scheduler_job_id=None,
             task_log="celery/linked.log", result=json.dumps({"notification_id": 1})),
        dict(id=2, task_type="legacy", scheduler_job_id="analysis_us_postmarket_review",
             task_log="../../outside.log", result="bad json"),
        dict(id=3, task_type="scheduled_us_postmarket_review", scheduler_job_id=None,
             task_log=None, result='{"notification_id":true}'),
        dict(id=4, task_type="scheduled_us_pre_close_review", scheduler_job_id="analysis_us_pre_close_review",
             task_log=None, result='{"notification_id":5}'),
        dict(id=5, task_type="scheduled_us_postmarket_review", scheduler_job_id=None,
             task_log=None, result='{"notification_id":99999999999999999999999999999}'),
        dict(id=6, task_type="scheduled_us_postmarket_review", scheduler_job_id=None,
             task_log="celery/linked-symlink.log", result=None),
        dict(id=7, task_type="scheduled_us_postmarket_review", scheduler_job_id=None,
             task_log=None, result='{"notification_id":1e1}'),
        dict(id=8, task_type="scheduled_us_postmarket_review", scheduler_job_id=None,
             task_log=None, result='{"notification_id":"10"}'),
    ])
    connection.execute(notification.insert(), [
        dict(id=1, title="Renamed old report", route_type="report", content="linked"),
        dict(id=2, title="美股收盘复盘 - 2026-10-30", route_type="report", content="old report"),
        dict(id=3, title="任务失败", route_type="system_error",
             content="\n- 类型：scheduled_us_postmarket_review\nfailed"),
        dict(id=4, title="US Postmarket Review", route_type="report", content="old English report"),
        dict(id=5, title="美股持仓复盘", route_type="report", content="keep private review"),
        dict(id=6, title="美股收盘复盘 - 2026-10-30", route_type="alert", content="keep unrelated route"),
        dict(id=7, title="Other task", route_type="system_error",
             content="\n- 类型：scheduled_us_pre_close_review\nkeep"),
        dict(id=8, title="Legacy title", route_type="report", content="# 美股收盘复盘 - 2026-10-29\nold"),
        dict(id=9, title="期权日报", route_type="report", content="keep options"),
        dict(id=10, title="美股收盘复盘优化讨论", route_type="report", content="keep unrelated content"),
    ])
    connection.execute(usage.insert(), [
        dict(id=1, call_type="us_postmarket_review"), dict(id=2, call_type="holdings_review"),
    ])
    connection.execute(timeline.insert(), [
        dict(id=1, entry_type="us_postmarket"), dict(id=2, entry_type="a_share_pre_close"),
    ])
    connection.execute(universe.insert(), [dict(id=1, key="us_daily_sync"), dict(id=2, key="us_index_etf")])
    connection.execute(members.insert(), [
        dict(id=1, universe_id=1, source="US_POSTMARKET_REVIEW"),
        dict(id=2, universe_id=1, source="CORE_INDEX_ETF"),
        dict(id=3, universe_id=2, source="US_POSTMARKET_REVIEW"),
    ])
    return task, notification, usage, timeline, members


def assert_cleaned(connection, tables):
    for table, ids in zip(tables[:4], ([4], [5, 6, 7, 9, 10], [2], [2])):
        assert connection.scalars(sa.select(table.c.id).order_by(table.c.id)).all() == ids
    members = tables[4]
    assert connection.execute(sa.select(members.c.id, members.c.source).order_by(members.c.id)).all() == [
        (1, "US_RESEARCH_CONTEXT"), (2, "CORE_INDEX_ETF"), (3, "US_POSTMARKET_REVIEW"),
    ]
    for name in ("stock_daily", "instrument", "portfolio_position", "holdings_review", "finance_events"):
        assert connection.scalar(sa.text(f"SELECT id FROM {name}")) == 1


def test_task_registration_and_orphaned_helpers_are_removed():
    from finance_analysis.tasks.celery.app import celery_app
    from finance_analysis.tasks.celery.schedule import (
        build_beat_schedule, build_task_routes, get_scheduled_task_definition,
    )

    celery_app.loader.import_default_modules()
    job = "analysis_us_postmarket_review"
    assert get_scheduled_task_definition(job) is None
    assert f"scheduled.{job}" not in celery_app.tasks
    assert f"scheduled.{job}" not in build_task_routes()
    assert all(row["task"] != f"scheduled.{job}" for row in build_beat_schedule().values())
    root = Path(__file__).parents[1] / "src/finance_analysis"
    assert not (root / "tasks/celery/jobs/us_postmarket_review").exists()
    assert not (root / "reporting/runtime.py").exists()
    assert not (root / "market_review/us_postmarket_symbols.py").exists()
    for task in ("analysis_a_share_pre_close_review", "analysis_us_pre_close_review", "earnings_outlook_final"):
        assert f"scheduled.{task}" in celery_app.tasks


@pytest.mark.parametrize("custom_audit", (False, True))
def test_cleanup_preserves_shared_facts_and_other_reports(connection, monkeypatch, tmp_path, custom_audit):
    module = migration()
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    clear_paths_cache()
    root = tmp_path / "data/logs"
    (root / "celery").mkdir(parents=True)
    linked = root / "celery/linked.log"
    old = root / "celery/美股收盘复盘_old.log"
    kept = root / "celery/美股持仓复盘_keep.log"
    outside = tmp_path / "outside.log"
    for path in (linked, old, kept, outside):
        path.write_text("keep")
    (root / "celery/美股收盘复盘_symlink.log").symlink_to(outside)
    (root / "celery/linked-symlink.log").symlink_to(kept)
    audit = tmp_path / "audit" if custom_audit else root / "llm"
    if custom_audit:
        monkeypatch.setenv("LLM_LOG_DIR", str(audit))
    else:
        monkeypatch.delenv("LLM_LOG_DIR", raising=False)
    audit.mkdir()
    retained = b'{"call_type":"holdings_review"}\ninvalid line\n\xff\n'
    for suffix in ("log", "jsonl"):
        (audit / f"mixed.{suffix}").write_bytes(b'{"call_type":"us_postmarket_review"}\n' + retained)
    reports = tmp_path / "data/reports/analysis"
    reports.mkdir(parents=True)
    old_report = reports / "us_postmarket_review_20260910.md"
    kept_report = reports / "holdings_review_20261031.md"
    similar_report = reports / "us_postmarket_review_notes.md"
    for path in (old_report, kept_report, similar_report):
        path.write_text("keep" if path != old_report else "old report")
    outside_report = tmp_path / "outside.md"
    outside_report.write_text("keep")
    report_link = reports / "us_postmarket_review_20260911.md"
    report_link.symlink_to(outside_report)
    tables = history_tables(connection)
    try:
        module.upgrade()
        module.upgrade()
        assert_cleaned(connection, tables)
        assert not linked.exists() and not old.exists()
        assert not old_report.exists()
        assert kept_report.read_text() == similar_report.read_text() == outside_report.read_text() == "keep"
        assert report_link.is_symlink()
        assert kept.read_text() == outside.read_text() == "keep"
        assert (root / "celery/linked-symlink.log").is_symlink()
        assert (root / "celery/美股收盘复盘_symlink.log").is_symlink()
        for suffix in ("log", "jsonl"):
            assert (audit / f"mixed.{suffix}").read_bytes() == retained
        with pytest.raises(RuntimeError, match="irreversible"):
            module.downgrade()
    finally:
        clear_paths_cache()


def test_empty_or_partial_database_cleanup_is_repeatable(connection, monkeypatch, tmp_path):
    module = migration()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_LOG_DIR", str(tmp_path / "audit"))
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    clear_paths_cache()
    try:
        module.upgrade()
        history_tables(connection)
        connection.execute(sa.text("DROP TABLE task"))
        module.upgrade()
        module.upgrade()
        assert connection.scalar(sa.text("SELECT count(*) FROM holdings_review")) == 1
    finally:
        clear_paths_cache()


def test_legacy_report_directory_symlink_preserves_files_outside_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LLM_LOG_DIR", str(tmp_path / "audit"))
    clear_paths_cache()
    outside = tmp_path / "external-reports"
    outside.mkdir()
    report = outside / "us_postmarket_review_20260910.md"
    report.write_text("keep external report")
    folder = tmp_path / "data/reports"
    folder.mkdir(parents=True)
    (folder / "analysis").symlink_to(outside, target_is_directory=True)
    try:
        migration()._purge_files([])
        assert report.read_text() == "keep external report"
    finally:
        clear_paths_cache()


def test_offline_sql_executes_on_postgresql_without_parsing_malformed_task_results(connection, monkeypatch):
    if connection.dialect.name != "postgresql":
        pytest.skip("Offline PostgreSQL SQL requires the isolated PostgreSQL test database")
    tables = history_tables(connection)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", dialect_opts={"paramstyle": "named"},
        opts={"as_sql": True, "literal_binds": True, "output_buffer": output},
    )
    module = migration()
    monkeypatch.setattr(module, "op", Operations(context))
    module.upgrade()
    sql = output.getvalue()
    connection.execute(sa.text(sql))
    connection.execute(sa.text(sql))
    assert_cleaned(connection, tables)

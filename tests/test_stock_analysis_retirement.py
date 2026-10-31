"""Retiring analysis must not strand jobs or disable shared research tasks."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.database.models.task import TaskRecord
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import get_scheduled_task_definition


def test_removed_jobs_are_not_registered_and_market_review_remains_available():
    celery_app.loader.import_default_modules()
    assert get_scheduled_task_definition("analysis_us_premarket") is None
    assert "scheduled.analysis_us_premarket" not in celery_app.tasks
    assert "analysis.run_stock_analysis" not in celery_app.tasks
    for name in (
        "scheduled.analysis_us_premarket_news",
        "scheduled.analysis_us_postmarket_review",
        "analysis.run_market_review",
    ):
        assert name in celery_app.tasks


def _exercise_migration(connection, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0083_retire_stock_analysis.py"
    spec = importlib.util.spec_from_file_location("retire_stock_analysis", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    table = TaskRecord.__table__
    table.create(connection)
    rows = [
        ("single", "stock_analysis", None, "pending"),
        ("scheduled", "scheduled_us_premarket", "analysis_us_premarket", "processing"),
        ("retry", "stock_analysis", None, "retrying"),
        ("legacy", "legacy", "analysis_us_premarket", "pending"),
        ("complete", "stock_analysis", None, "completed"),
        ("failed", "stock_analysis", None, "failed"),
        ("news", "scheduled_us_premarket_news", "analysis_us_premarket_news", "pending"),
        ("review", "market_review", None, "processing"),
    ]
    for task_id, task_type, job_id, status in rows:
        connection.execute(
            table.insert().values(
                task_id=task_id,
                task_type=task_type,
                scheduler_job_id=job_id,
                source="celery",
                status=status,
                result="saved result",
            )
        )
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    migration.upgrade()
    migration.upgrade()
    result = {row.task_id: row for row in connection.execute(sa.select(table))}
    for task_id in ("single", "scheduled", "retry", "legacy"):
        assert result[task_id].status == "cancelled"
        assert result[task_id].finished_at is not None
    for task_id, _, _, status in rows[4:]:
        assert result[task_id].status == status
    assert all(row.result == "saved result" for row in result.values())


def test_migration_cancels_only_unfinished_retired_jobs(monkeypatch):
    with sa.create_engine("sqlite://").begin() as connection:
        _exercise_migration(connection, monkeypatch)


def test_migration_cancels_only_unfinished_retired_jobs_postgresql(monkeypatch):
    url = os.getenv("STOCK_RETIREMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("STOCK_RETIREMENT_TEST_DATABASE_URL must point to an isolated test database")
    engine = sa.create_engine(url)
    schema = "stock_retirement_" + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            _exercise_migration(connection, monkeypatch)
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()

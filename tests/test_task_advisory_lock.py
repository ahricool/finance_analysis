"""Tests for the unified PostgreSQL task mutex implementation."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from finance_analysis.core.paths import PROJECT_ROOT
from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock, TaskAdvisoryLockId
from finance_analysis.tasks.lifecycle import track_task


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one(self) -> Any:
        return self.value


class _SharedAdvisoryDatabase:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.held: dict[tuple[int, int], _Connection] = {}
        self.connections: list[_Connection] = []
        self.waiting = threading.Event()
        self.fail_unlock = False

    def connect(self):
        connection = _Connection(self)
        self.connections.append(connection)
        return connection


class _Connection:
    def __init__(self, database: _SharedAdvisoryDatabase) -> None:
        self.database = database
        self.closed = False
        self.invalidated = False
        self.in_transaction = False
        self.commit_count = 0
        self.statements: list[str] = []

    def execute(self, statement, params):
        sql = str(statement)
        self.statements.append(sql)
        self.in_transaction = True
        key = (params["namespace"], params["lock_id"])
        with self.database.condition:
            if "pg_advisory_unlock" in sql:
                if self.database.fail_unlock:
                    raise RuntimeError("unlock failed")
                owned = self.database.held.get(key) is self
                if owned:
                    del self.database.held[key]
                    self.database.condition.notify_all()
                return _ScalarResult(owned)
            if "pg_try_advisory_lock" in sql:
                if key in self.database.held:
                    return _ScalarResult(False)
                self.database.held[key] = self
                return _ScalarResult(True)
            if "pg_advisory_lock" in sql:
                while key in self.database.held:
                    self.database.waiting.set()
                    self.database.condition.wait()
                self.database.held[key] = self
                return _ScalarResult(None)
        raise AssertionError(sql)

    def commit(self) -> None:
        self.commit_count += 1
        self.in_transaction = False

    def invalidate(self) -> None:
        self.invalidated = True

    def close(self) -> None:
        self.closed = True


def test_nonblocking_lock_commits_acquire_and_unlock_and_release_allows_next_run() -> None:
    database = _SharedAdvisoryDatabase()
    first = PostgreSQLAdvisoryLock(TaskAdvisoryLockId.CN_DAILY_MARKET_DATA_SYNC, database)
    second = PostgreSQLAdvisoryLock(TaskAdvisoryLockId.CN_DAILY_MARKET_DATA_SYNC, database)

    assert first.acquire() is True
    first_connection = database.connections[0]
    assert first_connection.in_transaction is False
    assert first_connection.commit_count == 1
    assert first_connection.closed is False

    assert second.acquire() is False
    assert database.connections[1].commit_count == 1
    assert database.connections[1].in_transaction is False
    assert database.connections[1].closed is True
    first.release()
    assert first_connection.commit_count == 2
    assert first_connection.closed is True

    assert second.acquire() is True
    second.release()
    assert database.held == {}


def test_blocking_lock_uses_pg_advisory_lock_and_commits_acquire() -> None:
    database = _SharedAdvisoryDatabase()
    lock = PostgreSQLAdvisoryLock(TaskAdvisoryLockId.STOCK_ANALYSIS, database, blocking=True)

    assert lock.acquire() is True
    connection = database.connections[0]
    assert any("pg_advisory_lock" in sql and "pg_try" not in sql for sql in connection.statements)
    assert connection.in_transaction is False
    assert connection.commit_count == 1
    lock.release()


def test_unlock_exception_invalidates_connection_before_close() -> None:
    database = _SharedAdvisoryDatabase()
    lock = PostgreSQLAdvisoryLock(TaskAdvisoryLockId.STOCK_ANALYSIS, database, blocking=True)
    assert lock.acquire() is True
    connection = database.connections[0]
    database.fail_unlock = True

    with pytest.raises(RuntimeError, match="unlock failed"):
        lock.release()

    assert connection.invalidated is True
    assert connection.closed is True


class _RecordingLifecycle:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.mutex = threading.Lock()

    def _record(self, event: str, kwargs: dict) -> None:
        with self.mutex:
            self.events.append((event, kwargs))

    def mark_processing(self, **kwargs):
        self._record("processing", kwargs)

    def mark_completed(self, **kwargs):
        self._record("completed", kwargs)

    def mark_skipped(self, **kwargs):
        self._record("skipped", kwargs)

    def mark_failed(self, **kwargs):
        self._record("failed", kwargs)

    def mark_progress(self, **kwargs):
        self._record("progress", kwargs)


class _ContendedLock:
    constructed: list[tuple[TaskAdvisoryLockId, bool]] = []

    def __init__(self, lock_id, *, blocking=False) -> None:
        self.lock_id = lock_id
        self.constructed.append((lock_id, blocking))

    def acquire(self) -> bool:
        return False

    def release(self) -> None:
        return None


@pytest.mark.parametrize(
    "lock_id",
    [
        TaskAdvisoryLockId.CN_DAILY_MARKET_DATA_SYNC,
        TaskAdvisoryLockId.US_DAILY_MARKET_DATA_SYNC,
        TaskAdvisoryLockId.CN_INTRADAY_ANALYSIS,
        TaskAdvisoryLockId.US_INTRADAY_ANALYSIS,
    ],
)
def test_each_scheduled_lock_contention_marks_task_record_skipped(lock_id) -> None:
    lifecycle = _RecordingLifecycle()
    calls: list[str] = []
    _ContendedLock.constructed.clear()

    @track_task(task_type="unit", task_name="Scheduled task", source="celery", advisory_lock_id=lock_id)
    def run() -> None:
        calls.append("ran")

    with patch("finance_analysis.tasks.lifecycle.get_task_lifecycle_service", return_value=lifecycle), patch(
        "finance_analysis.tasks.lifecycle.PostgreSQLAdvisoryLock", _ContendedLock
    ):
        assert run() is None

    assert calls == []
    assert _ContendedLock.constructed == [(lock_id, False)]
    assert [event for event, _ in lifecycle.events] == ["processing", "skipped"]


def test_different_stock_tasks_share_blocking_lock_and_execute_in_order() -> None:
    database = _SharedAdvisoryDatabase()
    lifecycle = _RecordingLifecycle()
    first_started = threading.Event()
    release_first = threading.Event()
    calls: list[str] = []

    @track_task(
        task_type="stock_analysis",
        task_name="Stock analysis",
        source="celery",
        task_id_getter=lambda stock_code: f"task-{stock_code}",
        advisory_lock_id=TaskAdvisoryLockId.STOCK_ANALYSIS,
        advisory_lock_blocking=True,
    )
    def analyze(stock_code: str) -> str:
        assert all(not connection.in_transaction for connection in database.held.values())
        calls.append(stock_code)
        if stock_code == "600519":
            first_started.set()
            assert release_first.wait(timeout=2)
        return stock_code

    def lock_factory(lock_id, *, blocking=False):
        return PostgreSQLAdvisoryLock(lock_id, database, blocking=blocking)

    results: list[str] = []
    with patch("finance_analysis.tasks.lifecycle.get_task_lifecycle_service", return_value=lifecycle), patch(
        "finance_analysis.tasks.lifecycle.PostgreSQLAdvisoryLock", side_effect=lock_factory
    ):
        first = threading.Thread(target=lambda: results.append(analyze("600519")))
        second = threading.Thread(target=lambda: results.append(analyze("NVDA")))
        first.start()
        assert first_started.wait(timeout=2)
        second.start()
        assert database.waiting.wait(timeout=2)
        assert calls == ["600519"]
        release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)

    assert calls == ["600519", "NVDA"]
    assert sorted(results) == ["600519", "NVDA"]
    assert [event for event, _ in lifecycle.events].count("completed") == 2
    assert [event for event, _ in lifecycle.events].count("skipped") == 0


def test_lock_ids_are_stable_and_readable() -> None:
    assert {item.name: item.value for item in TaskAdvisoryLockId} == {
        "CN_DAILY_MARKET_DATA_SYNC": 1,
        "US_DAILY_MARKET_DATA_SYNC": 2,
        "CN_INTRADAY_ANALYSIS": 3,
        "US_INTRADAY_ANALYSIS": 4,
        "STOCK_ANALYSIS": 5,
    }


def test_lock_declarations_are_exactly_four_nonblocking_scheduled_and_one_blocking_stock() -> None:
    from finance_analysis.tasks.celery.app import celery_app
    from finance_analysis.tasks.celery.metadata import STOCK_ANALYSIS_TASK
    from finance_analysis.tasks.celery.schedule import get_scheduled_task_definitions

    celery_app.loader.import_default_modules()
    locked = {}
    for definition in get_scheduled_task_definitions():
        run = celery_app.tasks[definition.celery_task_name].run
        lock_id = getattr(run, "_finance_advisory_lock_id", None)
        if lock_id is not None:
            locked[definition.job_id] = (
                lock_id,
                getattr(run, "_finance_advisory_lock_blocking", None),
            )

    assert locked == {
        "market_data_sync_cn_hk": (TaskAdvisoryLockId.CN_DAILY_MARKET_DATA_SYNC, False),
        "market_data_sync_us": (TaskAdvisoryLockId.US_DAILY_MARKET_DATA_SYNC, False),
        "analysis_a_share_intraday": (TaskAdvisoryLockId.CN_INTRADAY_ANALYSIS, False),
        "analysis_us_intraday": (TaskAdvisoryLockId.US_INTRADAY_ANALYSIS, False),
    }
    stock_run = celery_app.tasks[STOCK_ANALYSIS_TASK.celery_name].run
    assert stock_run._finance_advisory_lock_id is TaskAdvisoryLockId.STOCK_ANALYSIS
    assert stock_run._finance_advisory_lock_blocking is True


def test_no_scheduled_slot_or_legacy_task_lock_code_remains() -> None:
    project_root = Path(PROJECT_ROOT)
    source_root = project_root / "src" / "finance_analysis"
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))
    migration_text = (project_root / "alembic" / "versions" / "0036_unified_task_mutex.py").read_text(
        encoding="utf-8"
    )

    for token in ("scheduled_task_slot", "_scheduled_slot", "scheduled_slot_idempotency", "us_intraday:running"):
        assert token not in source_text
        assert token not in migration_text
    for relative_path in (
        "market_review/lock.py",
        "tasks/celery/jobs/a_share_intraday_analysis/lock.py",
        "tasks/celery/jobs/a_share_pre_close_review/lock.py",
        "tasks/celery/jobs/us_intraday_analysis/lock.py",
        "tasks/celery/jobs/us_postmarket_review/lock.py",
    ):
        assert not (source_root / relative_path).exists()

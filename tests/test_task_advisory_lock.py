"""Tests for PostgreSQL task mutexes and scheduled-slot idempotency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import patch

import pytest

from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock, TaskAdvisoryLockId
from finance_analysis.tasks.lifecycle import track_task


class _ScalarResult:
    def __init__(self, value: bool) -> None:
        self.value = value

    def scalar_one(self) -> bool:
        return self.value


class _SharedAdvisoryDatabase:
    def __init__(self) -> None:
        self.held: set[tuple[int, int]] = set()
        self.connections: list[_Connection] = []

    def connect(self):
        connection = _Connection(self)
        self.connections.append(connection)
        return connection


class _Connection:
    def __init__(self, database: _SharedAdvisoryDatabase) -> None:
        self.database = database
        self.closed = False

    def execute(self, statement, params):
        sql = str(statement)
        key = (params["namespace"], params["lock_id"])
        if "pg_try_advisory_lock" in sql:
            if key in self.database.held:
                return _ScalarResult(False)
            self.database.held.add(key)
            return _ScalarResult(True)
        if "pg_advisory_unlock" in sql:
            existed = key in self.database.held
            self.database.held.discard(key)
            return _ScalarResult(existed)
        raise AssertionError(sql)

    def close(self) -> None:
        self.closed = True


def test_two_worker_connections_only_one_acquires_and_release_allows_next_run() -> None:
    database = _SharedAdvisoryDatabase()
    first = PostgreSQLAdvisoryLock(TaskAdvisoryLockId.CN_DAILY_MARKET_DATA_SYNC, database)
    second = PostgreSQLAdvisoryLock(TaskAdvisoryLockId.CN_DAILY_MARKET_DATA_SYNC, database)

    assert first.acquire() is True
    assert second.acquire() is False
    assert len(database.connections) == 2
    assert database.connections[1].closed is True

    first.release()
    assert second.acquire() is True
    second.release()
    assert database.held == set()


class _RecordingLifecycle:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def mark_processing(self, **kwargs):
        self.events.append(("processing", kwargs))

    def mark_completed(self, **kwargs):
        self.events.append(("completed", kwargs))

    def mark_skipped(self, **kwargs):
        self.events.append(("skipped", kwargs))

    def mark_failed(self, **kwargs):
        self.events.append(("failed", kwargs))

    def mark_progress(self, **kwargs):
        self.events.append(("progress", kwargs))


class _ContendedLock:
    def __init__(self, lock_id) -> None:
        self.lock_id = lock_id
        self.released = False

    def acquire(self) -> bool:
        return False

    def release(self) -> None:
        self.released = True


def test_advisory_lock_contention_marks_task_record_skipped() -> None:
    lifecycle = _RecordingLifecycle()
    calls: list[str] = []

    @track_task(
        task_type="unit",
        task_name="Locked task",
        source="celery",
        advisory_lock_id=TaskAdvisoryLockId.US_DAILY_MARKET_DATA_SYNC,
    )
    def run() -> None:
        calls.append("ran")

    with patch("finance_analysis.tasks.lifecycle.get_task_lifecycle_service", return_value=lifecycle), patch(
        "finance_analysis.tasks.lifecycle.PostgreSQLAdvisoryLock", _ContendedLock
    ):
        assert run() is None

    assert calls == []
    assert [event for event, _ in lifecycle.events] == ["processing", "skipped"]
    assert "US_DAILY_MARKET_DATA_SYNC" in lifecycle.events[-1][1]["message"]


def test_task_without_mutex_does_not_touch_advisory_lock() -> None:
    lifecycle = _RecordingLifecycle()

    @track_task(task_type="unit", task_name="Unlocked task", source="celery")
    def run() -> str:
        return "ok"

    with patch("finance_analysis.tasks.lifecycle.get_task_lifecycle_service", return_value=lifecycle), patch(
        "finance_analysis.tasks.lifecycle.PostgreSQLAdvisoryLock",
        side_effect=AssertionError("unlocked task must not construct a mutex"),
    ):
        assert run() == "ok"

    assert [event for event, _ in lifecycle.events] == ["processing", "completed"]


class _AcquiredLock:
    def __init__(self, lock_id) -> None:
        self.lock_id = lock_id

    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        return None


@dataclass
class _SlotRepository:
    completed: set[tuple[str, object, datetime]]

    def was_completed(self, *, job_id, trading_date, scheduled_slot) -> bool:
        return (job_id, trading_date, scheduled_slot) in self.completed

    def record_completed(self, *, job_id, trading_date, scheduled_slot, task_id) -> bool:
        del task_id
        key = (job_id, trading_date, scheduled_slot)
        if key in self.completed:
            return False
        self.completed.add(key)
        return True


@pytest.mark.parametrize(
    ("job_id", "lock_id", "first_slot", "second_slot"),
    [
        (
            "analysis_a_share_intraday",
            TaskAdvisoryLockId.CN_INTRADAY_ANALYSIS,
            "2026-08-31T09:45:00+08:00",
            "2026-08-31T10:45:00+08:00",
        ),
        (
            "analysis_us_intraday",
            TaskAdvisoryLockId.US_INTRADAY_ANALYSIS,
            "2026-08-31T09:45:00-04:00",
            "2026-08-31T10:15:00-04:00",
        ),
    ],
)
def test_intraday_same_slot_is_skipped_but_different_slot_runs(
    job_id: str,
    lock_id: TaskAdvisoryLockId,
    first_slot: str,
    second_slot: str,
) -> None:
    lifecycle = _RecordingLifecycle()
    slots = _SlotRepository(set())
    calls: list[str] = []

    @track_task(
        task_type="unit",
        task_name="Intraday task",
        source="celery",
        trigger_source="scheduler",
        scheduler_job_id=job_id,
        strip_lifecycle_kwargs=True,
        advisory_lock_id=lock_id,
        scheduled_slot_idempotency=True,
    )
    def run(**_):
        calls.append("ran")
        return {"ok": True}

    patches = (
        patch("finance_analysis.tasks.lifecycle.get_task_lifecycle_service", return_value=lifecycle),
        patch("finance_analysis.tasks.lifecycle.PostgreSQLAdvisoryLock", _AcquiredLock),
        patch("finance_analysis.tasks.lifecycle.ScheduledTaskSlotRepository", return_value=slots),
    )
    with patches[0], patches[1], patches[2]:
        assert run(_trigger_source="scheduler", _scheduled_slot=first_slot) == {"ok": True}
        assert run(_trigger_source="scheduler", _scheduled_slot=first_slot) is None
        assert run(_trigger_source="scheduler", _scheduled_slot=second_slot) == {"ok": True}

    assert calls == ["ran", "ran"]
    assert [event for event, _ in lifecycle.events].count("skipped") == 1


def test_only_four_scheduled_tasks_declare_advisory_mutexes() -> None:
    from finance_analysis.tasks.celery.app import celery_app
    from finance_analysis.tasks.celery.schedule import get_scheduled_task_definitions

    celery_app.loader.import_default_modules()
    locked = {}
    slotted = set()
    for definition in get_scheduled_task_definitions():
        run = celery_app.tasks[definition.celery_task_name].run
        lock_id = getattr(run, "_finance_advisory_lock_id", None)
        if lock_id is not None:
            locked[definition.job_id] = lock_id
        if getattr(run, "_finance_scheduled_slot_idempotency", False):
            slotted.add(definition.job_id)

    assert locked == {
        "market_data_sync_cn_hk": TaskAdvisoryLockId.CN_DAILY_MARKET_DATA_SYNC,
        "market_data_sync_us": TaskAdvisoryLockId.US_DAILY_MARKET_DATA_SYNC,
        "analysis_a_share_intraday": TaskAdvisoryLockId.CN_INTRADAY_ANALYSIS,
        "analysis_us_intraday": TaskAdvisoryLockId.US_INTRADAY_ANALYSIS,
    }
    assert slotted == {"analysis_a_share_intraday", "analysis_us_intraday"}

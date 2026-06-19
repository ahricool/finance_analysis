from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services.task_center import (
    DuplicateScheduledTaskError,
    ScheduledTaskService,
    SchedulerUnavailableError,
    TaskQueryService,
)
from src.time_utils import utc_now


class _FakeScheduler:
    running = True

    def __init__(self):
        self.jobs = {
            "analysis_us_premarket": SimpleNamespace(id="analysis_us_premarket", next_run_time=utc_now()),
            "analysis_daily": SimpleNamespace(id="analysis_daily", next_run_time=utc_now()),
        }
        self.added_jobs = []

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def add_job(self, func, trigger, **kwargs):
        self.added_jobs.append({"func": func, "trigger": trigger, **kwargs})


class _FakeTaskRepo:
    ACTIVE_STATUSES = ("pending", "processing", "retrying")

    def __init__(self, records=None):
        self.records = list(records or [])
        self.updated = []

    def get_latest_by_scheduler_job_ids(self, job_ids):
        result = {}
        for job_id in job_ids:
            matching = [record for record in self.records if record.scheduler_job_id == job_id]
            if matching:
                result[job_id] = sorted(matching, key=lambda record: record.created_at, reverse=True)[0]
        return result

    def get_active_by_scheduler_job_id(self, job_id):
        for record in self.records:
            if record.scheduler_job_id == job_id and record.status in self.ACTIVE_STATUSES:
                return record
        return None

    def create_pending_or_get_duplicate(self, **kwargs):
        for record in self.records:
            if record.dedupe_key == kwargs.get("dedupe_key") and record.status in self.ACTIVE_STATUSES:
                return record, False
        record = SimpleNamespace(
            id=len(self.records) + 1,
            result=None,
            error=None,
            task_log=None,
            parent_task_id=None,
            retry_count=0,
            created_at=utc_now(),
            started_at=None,
            finished_at=None,
            updated_at=utc_now(),
            **kwargs,
            status="pending",
        )
        self.records.append(record)
        return record, True

    def update_status(self, **kwargs):
        self.updated.append(kwargs)

    def list_tasks(self, *, limit=20, offset=0, statuses=None, uid=None, **filters):
        rows = self._filtered(statuses=statuses, uid=uid, **filters)
        return rows[offset: offset + limit]

    def count_tasks(self, *, statuses=None, uid=None, **filters):
        return len(self._filtered(statuses=statuses, uid=uid, **filters))

    def count_by_status(self, *, uid=None, **filters):
        counts = {}
        for record in self._filtered(uid=uid, **filters):
            counts[record.status] = counts.get(record.status, 0) + 1
        return counts

    def get_by_task_id(self, task_id):
        for record in self.records:
            if record.task_id == task_id:
                return record
        return None

    def _filtered(self, *, statuses=None, uid=None, **_):
        rows = list(self.records)
        if statuses:
            status_set = set(statuses)
            rows = [record for record in rows if record.status in status_set]
        if uid is not None:
            rows = [record for record in rows if record.uid == uid]
        return sorted(rows, key=lambda record: record.created_at, reverse=True)


def _record(task_id, *, uid, status="completed", scheduler_job_id=None, payload=None, error=None):
    return SimpleNamespace(
        id=1,
        task_id=task_id,
        task_type="unit",
        task_name="Unit Task",
        uid=uid,
        source="apscheduler" if scheduler_job_id else "celery_manual",
        trigger_source="scheduler" if scheduler_job_id else "api",
        triggered_by_uid=None,
        status=status,
        progress=100,
        message="done",
        payload=payload,
        result='{"ok": true}',
        error=error,
        task_log="internal/task.log",
        parent_task_id=None,
        retry_count=0,
        scheduler_job_id=scheduler_job_id,
        dedupe_key=f"scheduled:{scheduler_job_id}" if scheduler_job_id else None,
        created_at=utc_now(),
        started_at=utc_now(),
        finished_at=utc_now(),
        updated_at=utc_now(),
    )


def test_scheduled_tasks_include_latest_run_and_next_run_time():
    repo = _FakeTaskRepo([_record("task-1", uid=None, scheduler_job_id="analysis_us_premarket")])
    service = ScheduledTaskService(repository=repo, scheduler=_FakeScheduler())

    items = service.list_scheduled_tasks()
    premarket = next(item for item in items if item["job_id"] == "analysis_us_premarket")

    assert premarket["name"] == "美股盘前分析"
    assert premarket["scheduler_status"] == "active"
    assert premarket["next_run_time"]
    assert premarket["latest_run"]["task_id"] == "task-1"


def test_manual_run_creates_pending_record_and_submits_one_off_job_without_calling_function():
    repo = _FakeTaskRepo()
    scheduler = _FakeScheduler()
    service = ScheduledTaskService(repository=repo, scheduler=scheduler)

    result = service.run_scheduled_task_now(job_id="analysis_us_premarket", triggered_by_uid=7)

    assert result["status"] == "pending"
    assert repo.records[0].trigger_source == "manual"
    assert repo.records[0].triggered_by_uid == 7
    assert repo.records[0].scheduler_job_id == "analysis_us_premarket"
    assert len(scheduler.added_jobs) == 1
    assert scheduler.added_jobs[0]["trigger"] == "date"
    assert scheduler.added_jobs[0]["kwargs"]["task_id"] == result["task_id"]


def test_manual_run_returns_duplicate_when_job_active():
    active = _record("active-task", uid=None, status="processing", scheduler_job_id="analysis_us_premarket")
    service = ScheduledTaskService(repository=_FakeTaskRepo([active]), scheduler=_FakeScheduler())

    with pytest.raises(DuplicateScheduledTaskError) as exc:
        service.run_scheduled_task_now(job_id="analysis_us_premarket", triggered_by_uid=7)

    assert exc.value.existing_task_id == "active-task"


def test_manual_run_requires_running_scheduler():
    scheduler = _FakeScheduler()
    scheduler.running = False
    service = ScheduledTaskService(repository=_FakeTaskRepo(), scheduler=scheduler)

    with pytest.raises(SchedulerUnavailableError):
        service.run_scheduled_task_now(job_id="analysis_us_premarket", triggered_by_uid=7)


def test_task_run_list_scopes_regular_user_and_keeps_admin_unscoped():
    repo = _FakeTaskRepo([
        _record("user-task", uid=10),
        _record("other-task", uid=11),
        _record("system-task", uid=None, scheduler_job_id="analysis_daily"),
    ])
    service = TaskQueryService(repository=repo, db=SimpleNamespace())
    service._load_users = lambda uids: {}

    user_payload = service.list_runs(is_admin=False, current_uid=10, page=1, page_size=20)
    admin_payload = service.list_runs(is_admin=True, current_uid=1, page=1, page_size=20)

    assert [item["task_id"] for item in user_payload["items"]] == ["user-task"]
    assert admin_payload["total"] == 3
    assert admin_payload["statistics"]["completed"] == 3


def test_task_detail_hides_sensitive_fields_for_regular_user():
    record = _record("user-task", uid=10, payload='{"secret": "***"}', error="Traceback\nValueError: bad token")
    service = TaskQueryService(repository=_FakeTaskRepo([record]), db=SimpleNamespace())
    service._load_users = lambda uids: {}

    user_detail = service.get_run_detail(task_id="user-task", is_admin=False, current_uid=10)
    admin_detail = service.get_run_detail(task_id="user-task", is_admin=True, current_uid=1)

    assert user_detail["payload"] is None
    assert user_detail["task_log"] is None
    assert user_detail["error"] == "ValueError: bad token"
    assert admin_detail["payload"] == {"secret": "***"}
    assert admin_detail["task_log"] == "internal/task.log"


def test_regular_user_cannot_read_other_user_detail():
    service = TaskQueryService(repository=_FakeTaskRepo([_record("other-task", uid=11)]), db=SimpleNamespace())

    assert service.get_run_detail(task_id="other-task", is_admin=False, current_uid=10) is None

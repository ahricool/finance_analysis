# -*- coding: utf-8 -*-
"""Task center services for scheduled jobs and task run queries."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select

from finance_analysis.database.session import DatabaseManager
from finance_analysis.database.models.task import TaskRecord
from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.task_record import TaskRecordRepository
from finance_analysis.tasks.scheduler import (
    get_embedded_analysis_scheduler,
    get_scheduled_task_definition,
    get_scheduled_task_definitions,
)
from finance_analysis.tasks.lifecycle import MAX_PAYLOAD_CHARS, TaskExecutionStatus, _json_summary
from finance_analysis.core.time import utc_isoformat, utc_now

TASK_STATUSES = (
    "pending",
    "processing",
    "completed",
    "failed",
    "skipped",
    "cancelled",
    "retrying",
)


class SchedulerUnavailableError(RuntimeError):
    """Raised when the embedded APScheduler is not running."""


class ScheduledTaskNotFoundError(KeyError):
    """Raised when a scheduled task definition does not exist."""


class ManualRunNotAllowedError(RuntimeError):
    """Raised when a scheduled task does not allow manual execution."""


@dataclass
class DuplicateScheduledTaskError(RuntimeError):
    existing_task_id: str
    message: str


def _duration_seconds(record: TaskRecord) -> Optional[float]:
    if not record.started_at or not record.finished_at:
        return None
    return max(0.0, (record.finished_at - record.started_at).total_seconds())


def _safe_json_loads(value: Optional[str]) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _sanitize_error_for_user(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return text[:500]
    return lines[-1][:500]


class ScheduledTaskService:
    """Read scheduled job metadata and submit one-off manual runs."""

    def __init__(
        self,
        repository: Optional[TaskRecordRepository] = None,
        scheduler: Optional[Any] = None,
    ):
        self.repository = repository or TaskRecordRepository()
        self.scheduler = scheduler

    def list_scheduled_tasks(self) -> List[Dict[str, Any]]:
        scheduler = self._get_scheduler(required=False)
        definitions = get_scheduled_task_definitions()
        latest_by_job = self.repository.get_latest_by_scheduler_job_ids(item.job_id for item in definitions)
        items: List[Dict[str, Any]] = []
        for definition in definitions:
            job = scheduler.get_job(definition.job_id) if scheduler is not None else None
            scheduler_status = self._scheduler_status(scheduler, job)
            latest = latest_by_job.get(definition.job_id)
            items.append(
                {
                    "job_id": definition.job_id,
                    "name": definition.name,
                    "description": definition.description,
                    "task_type": definition.task_type,
                    "schedule": definition.schedule,
                    "timezone": definition.timezone,
                    "scheduler_status": scheduler_status,
                    "next_run_time": utc_isoformat(job.next_run_time) if job is not None else None,
                    "allow_manual_run": definition.allow_manual_run,
                    "latest_run": self._latest_run_payload(latest) if latest else None,
                }
            )
        return items

    def run_scheduled_task_now(self, *, job_id: str, triggered_by_uid: int) -> Dict[str, Any]:
        definition = get_scheduled_task_definition(job_id)
        if definition is None:
            raise ScheduledTaskNotFoundError(job_id)
        if not definition.allow_manual_run:
            raise ManualRunNotAllowedError(f"{definition.name} 不支持手动执行")

        scheduler = self._get_scheduler(required=True)
        if scheduler.get_job(job_id) is None:
            raise SchedulerUnavailableError(f"Scheduler job {job_id} is not registered")

        existing = self.repository.get_active_by_scheduler_job_id(job_id)
        if existing is not None:
            raise DuplicateScheduledTaskError(existing.task_id, f"{definition.name} 正在执行中")

        task_id = uuid.uuid4().hex
        dedupe_key = f"scheduled:{job_id}"
        payload = {"job_id": job_id, "trigger_source": "manual", "triggered_by_uid": triggered_by_uid}
        record, created = self.repository.create_pending_or_get_duplicate(
            task_id=task_id,
            task_type=definition.task_type,
            task_name=definition.name,
            source="apscheduler",
            trigger_source="manual",
            triggered_by_uid=triggered_by_uid,
            scheduler_job_id=definition.job_id,
            dedupe_key=dedupe_key,
            payload=_json_summary(payload, limit=MAX_PAYLOAD_CHARS),
            message="管理员手动提交，等待调度器执行",
            progress=0,
        )
        if not created:
            raise DuplicateScheduledTaskError(record.task_id, f"{definition.name} 正在执行中")

        one_off_job_id = f"manual:{job_id}:{task_id}"
        try:
            scheduler.add_job(
                definition.func,
                "date",
                id=one_off_job_id,
                run_date=utc_now(),
                kwargs={
                    "task_id": task_id,
                    "_trigger_source": "manual",
                    "_triggered_by_uid": triggered_by_uid,
                },
                replace_existing=False,
                misfire_grace_time=60,
            )
        except Exception as exc:
            self.repository.update_status(
                task_id=task_id,
                status=TaskExecutionStatus.CANCELLED.value,
                task_type=definition.task_type,
                task_name=definition.name,
                source="apscheduler",
                trigger_source="manual",
                triggered_by_uid=triggered_by_uid,
                scheduler_job_id=definition.job_id,
                message=f"调度器提交失败: {exc}",
                finished_at=utc_now(),
                progress=100,
            )
            raise SchedulerUnavailableError(str(exc)) from exc

        return {
            "task_id": task_id,
            "job_id": definition.job_id,
            "status": "pending",
            "message": "任务已提交",
        }

    @staticmethod
    def _scheduler_status(scheduler: Optional[Any], job: Optional[Any]) -> str:
        if scheduler is None or not getattr(scheduler, "running", False):
            return "unavailable"
        if job is None:
            return "unavailable"
        if getattr(job, "next_run_time", None) is None:
            return "paused"
        return "active"

    @staticmethod
    def _latest_run_payload(record: TaskRecord) -> Dict[str, Any]:
        return {
            "task_id": record.task_id,
            "status": record.status,
            "started_at": utc_isoformat(record.started_at),
            "finished_at": utc_isoformat(record.finished_at),
            "duration_seconds": _duration_seconds(record),
            "message": record.message,
        }

    def _get_scheduler(self, *, required: bool) -> Optional[Any]:
        scheduler = self.scheduler if self.scheduler is not None else get_embedded_analysis_scheduler()
        if required and (scheduler is None or not getattr(scheduler, "running", False)):
            raise SchedulerUnavailableError("APScheduler is not running")
        return scheduler


class TaskQueryService:
    """Query task runs with role-aware field shaping."""

    def __init__(
        self,
        repository: Optional[TaskRecordRepository] = None,
        db: Optional[DatabaseManager] = None,
    ):
        self.repository = repository or TaskRecordRepository()
        self.db = db or DatabaseManager.get_instance()

    def list_runs(
        self,
        *,
        is_admin: bool,
        current_uid: int,
        page: int,
        page_size: int,
        statuses: Optional[Iterable[str]] = None,
        uid: Optional[int] = None,
        task_type: Optional[str] = None,
        source: Optional[str] = None,
        trigger_source: Optional[str] = None,
        scheduler_job_id: Optional[str] = None,
        keyword: Optional[str] = None,
        started_from: Optional[datetime] = None,
        started_to: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        scoped_uid = uid if is_admin else current_uid
        offset = (max(1, page) - 1) * max(1, page_size)
        records = self.repository.list_tasks(
            limit=page_size,
            offset=offset,
            statuses=statuses,
            uid=scoped_uid,
            task_type=task_type,
            source=source,
            trigger_source=trigger_source,
            scheduler_job_id=scheduler_job_id,
            keyword=keyword,
            started_from=started_from,
            started_to=started_to,
        )
        total = self.repository.count_tasks(
            statuses=statuses,
            uid=scoped_uid,
            task_type=task_type,
            source=source,
            trigger_source=trigger_source,
            scheduler_job_id=scheduler_job_id,
            keyword=keyword,
            started_from=started_from,
            started_to=started_to,
        )
        statistics = self.repository.count_by_status(
            uid=scoped_uid,
            task_type=task_type,
            source=source,
            trigger_source=trigger_source,
            scheduler_job_id=scheduler_job_id,
            keyword=keyword,
            started_from=started_from,
            started_to=started_to,
        )
        users = self._load_users(record.uid for record in records)
        return {
            "items": [self._record_payload(record, is_admin=is_admin, users=users, detail=False) for record in records],
            "total": total,
            "page": max(1, page),
            "page_size": page_size,
            "statistics": {status: int(statistics.get(status, 0)) for status in TASK_STATUSES},
        }

    def get_run_detail(self, *, task_id: str, is_admin: bool, current_uid: int) -> Optional[Dict[str, Any]]:
        record = self.repository.get_by_task_id(task_id)
        if record is None:
            return None
        if not is_admin and record.uid != current_uid:
            return None
        users = self._load_users([record.uid, record.triggered_by_uid])
        return self._record_payload(record, is_admin=is_admin, users=users, detail=True)

    def _record_payload(
        self,
        record: TaskRecord,
        *,
        is_admin: bool,
        users: Dict[int, Dict[str, str]],
        detail: bool,
    ) -> Dict[str, Any]:
        payload = {
            "id": record.id,
            "task_id": record.task_id,
            "task_name": record.task_name,
            "task_type": record.task_type,
            "uid": record.uid,
            "user": users.get(record.uid) if record.uid is not None else None,
            "source": record.source,
            "trigger_source": record.trigger_source,
            "triggered_by_uid": record.triggered_by_uid,
            "triggered_by_user": users.get(record.triggered_by_uid) if record.triggered_by_uid is not None else None,
            "status": record.status,
            "progress": record.progress,
            "message": record.message,
            "scheduler_job_id": record.scheduler_job_id,
            "parent_task_id": record.parent_task_id,
            "retry_count": record.retry_count,
            "created_at": utc_isoformat(record.created_at),
            "started_at": utc_isoformat(record.started_at),
            "finished_at": utc_isoformat(record.finished_at),
            "updated_at": utc_isoformat(record.updated_at),
            "duration_seconds": _duration_seconds(record),
        }
        if not detail:
            return payload

        if is_admin:
            payload.update(
                {
                    "payload": _safe_json_loads(record.payload),
                    "result": _safe_json_loads(record.result),
                    "error": record.error,
                    "task_log": record.task_log,
                }
            )
        else:
            payload.update(
                {
                    "payload": None,
                    "result": _safe_json_loads(record.result),
                    "error": _sanitize_error_for_user(record.error),
                    "task_log": None,
                }
            )
        return payload

    def _load_users(self, uids: Iterable[Optional[int]]) -> Dict[int, Dict[str, str]]:
        uid_list = sorted({int(uid) for uid in uids if uid is not None})
        if not uid_list:
            return {}
        with self.db.get_session() as session:
            rows = session.execute(select(User).where(User.id.in_(uid_list))).scalars().all()
            return {
                row.id: {
                    "uid": row.id,
                    "username": row.username,
                    "email": row.email,
                    "role": row.role,
                }
                for row in rows
            }

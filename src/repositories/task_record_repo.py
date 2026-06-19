# -*- coding: utf-8 -*-
"""Repository for persistent task execution records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.session import DatabaseManager
from src.models.task import TaskRecord
from src.time_utils import utc_now


class TaskRecordRepository:
    """Small data-access layer around the task execution history table."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def ensure_record(
        self,
        *,
        task_id: str,
        task_type: str,
        source: str,
        status: str,
        task_name: Optional[str] = None,
        uid: Optional[int] = None,
        payload: Optional[str] = None,
        message: Optional[str] = None,
        progress: Optional[int] = None,
        task_log: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        retry_count: Optional[int] = None,
        scheduler_job_id: Optional[str] = None,
    ) -> TaskRecord:
        """Create a record if absent, otherwise fill missing metadata and update status."""

        now = utc_now()
        with self.db.session_scope() as session:
            existing = self._get_for_update(session, task_id)
            if existing is not None:
                self._apply_metadata(
                    existing,
                    task_type=task_type,
                    source=source,
                    task_name=task_name,
                    uid=uid,
                    payload=payload,
                    message=message,
                    progress=progress,
                    task_log=task_log,
                    parent_task_id=parent_task_id,
                    retry_count=retry_count,
                    scheduler_job_id=scheduler_job_id,
                )
                if self._can_apply_status(existing.status, status):
                    existing.status = status
                existing.updated_at = now
                session.flush()
                return self._detach(session, existing)

            record = TaskRecord(
                task_id=task_id,
                task_type=task_type,
                task_name=task_name,
                uid=uid,
                source=source,
                status=status,
                progress=0 if progress is None else progress,
                message=message,
                payload=payload,
                task_log=task_log,
                parent_task_id=parent_task_id,
                retry_count=0 if retry_count is None else retry_count,
                scheduler_job_id=scheduler_job_id,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return self.ensure_record(
                    task_id=task_id,
                    task_type=task_type,
                    source=source,
                    status=status,
                    task_name=task_name,
                    uid=uid,
                    payload=payload,
                    message=message,
                    progress=progress,
                    task_log=task_log,
                    parent_task_id=parent_task_id,
                    retry_count=retry_count,
                    scheduler_job_id=scheduler_job_id,
                )
            return self._detach(session, record)

    def update_status(
        self,
        *,
        task_id: str,
        status: str,
        task_type: Optional[str] = None,
        source: Optional[str] = None,
        task_name: Optional[str] = None,
        uid: Optional[int] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        payload: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None,
        task_log: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        parent_task_id: Optional[str] = None,
        retry_count: Optional[int] = None,
        scheduler_job_id: Optional[str] = None,
    ) -> Optional[TaskRecord]:
        """Idempotently update task status and selected fields."""

        now = utc_now()
        with self.db.session_scope() as session:
            record = self._get_for_update(session, task_id)
            if record is None:
                if task_type is None or source is None:
                    return None
                record = TaskRecord(
                    task_id=task_id,
                    task_type=task_type,
                    task_name=task_name,
                    uid=uid,
                    source=source,
                    status=status,
                    progress=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
                try:
                    session.flush()
                except IntegrityError:
                    session.rollback()
                    return self.update_status(
                        task_id=task_id,
                        status=status,
                        task_type=task_type,
                        source=source,
                        task_name=task_name,
                        uid=uid,
                        progress=progress,
                        message=message,
                        payload=payload,
                        result=result,
                        error=error,
                        task_log=task_log,
                        started_at=started_at,
                        finished_at=finished_at,
                        parent_task_id=parent_task_id,
                        retry_count=retry_count,
                        scheduler_job_id=scheduler_job_id,
                    )

            self._apply_metadata(
                record,
                task_type=task_type,
                source=source,
                task_name=task_name,
                uid=uid,
                payload=payload,
                message=message,
                progress=progress,
                task_log=task_log,
                parent_task_id=parent_task_id,
                retry_count=retry_count,
                scheduler_job_id=scheduler_job_id,
            )
            if self._can_apply_status(record.status, status):
                record.status = status
            if result is not None:
                record.result = result
            if error is not None:
                record.error = error
            if started_at is not None and record.started_at is None:
                record.started_at = started_at
            if finished_at is not None:
                record.finished_at = finished_at
            record.updated_at = now
            session.flush()
            return self._detach(session, record)

    def get_by_task_id(self, task_id: str) -> Optional[TaskRecord]:
        with self.db.get_session() as session:
            record = session.execute(select(TaskRecord).where(TaskRecord.task_id == task_id)).scalar_one_or_none()
            return self._detach(session, record) if record is not None else None

    def list_recent(
        self,
        *,
        limit: int = 50,
        statuses: Optional[Iterable[str]] = None,
        uid: Optional[int] = None,
    ) -> List[TaskRecord]:
        with self.db.get_session() as session:
            query = select(TaskRecord)
            conditions = []
            if statuses:
                conditions.append(TaskRecord.status.in_(list(statuses)))
            if uid is not None:
                conditions.append(TaskRecord.uid == uid)
            if conditions:
                query = query.where(*conditions)
            rows = session.execute(
                query.order_by(desc(TaskRecord.created_at)).limit(limit)
            ).scalars().all()
            return [self._detach(session, row) for row in rows]

    @staticmethod
    def to_dict(record: TaskRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "task_id": record.task_id,
            "task_type": record.task_type,
            "task_name": record.task_name,
            "uid": record.uid,
            "source": record.source,
            "status": record.status,
            "progress": record.progress,
            "message": record.message,
            "payload": record.payload,
            "result": record.result,
            "error": record.error,
            "task_log": record.task_log,
            "parent_task_id": record.parent_task_id,
            "retry_count": record.retry_count,
            "scheduler_job_id": record.scheduler_job_id,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _get_for_update(session: Session, task_id: str) -> Optional[TaskRecord]:
        return session.execute(
            select(TaskRecord).where(TaskRecord.task_id == task_id).with_for_update()
        ).scalar_one_or_none()

    @staticmethod
    def _detach(session: Session, record: TaskRecord) -> TaskRecord:
        session.expunge(record)
        return record

    @staticmethod
    def _apply_metadata(record: TaskRecord, **values: Any) -> None:
        for key, value in values.items():
            if value is None:
                continue
            if key == "progress":
                value = max(0, min(100, int(value)))
            setattr(record, key, value)

    @staticmethod
    def _can_apply_status(current: str, new: str) -> bool:
        if current == new:
            return True
        terminal = {"completed", "failed", "skipped", "cancelled"}
        if current in terminal and new not in terminal:
            return False
        return True

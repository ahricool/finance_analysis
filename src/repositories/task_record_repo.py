# -*- coding: utf-8 -*-
"""Repository for persistent task execution records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.session import DatabaseManager
from src.models.task import TaskRecord
from src.time_utils import utc_now


class TaskRecordRepository:
    """Small data-access layer around the task execution history table."""

    ACTIVE_STATUSES = ("pending", "processing", "retrying")

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
        dedupe_key: Optional[str] = None,
        trigger_source: Optional[str] = None,
        triggered_by_uid: Optional[int] = None,
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
                    dedupe_key=dedupe_key,
                    trigger_source=trigger_source,
                    triggered_by_uid=triggered_by_uid,
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
                dedupe_key=dedupe_key,
                trigger_source=trigger_source,
                triggered_by_uid=triggered_by_uid,
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
                    dedupe_key=dedupe_key,
                    trigger_source=trigger_source,
                    triggered_by_uid=triggered_by_uid,
                )
            return self._detach(session, record)

    def create_pending_or_get_duplicate(
        self,
        *,
        task_id: str,
        task_type: str,
        source: str,
        dedupe_key: Optional[str],
        task_name: Optional[str] = None,
        uid: Optional[int] = None,
        payload: Optional[str] = None,
        message: Optional[str] = None,
        progress: int = 0,
        task_log: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        retry_count: int = 0,
        scheduler_job_id: Optional[str] = None,
        trigger_source: Optional[str] = None,
        triggered_by_uid: Optional[int] = None,
    ) -> Tuple[TaskRecord, bool]:
        """
        Create a pending task record.

        Returns ``(record, created)``. If a database uniqueness constraint finds
        another in-flight row with the same dedupe key, returns that existing row
        with ``created=False``.
        """

        now = utc_now()
        with self.db.session_scope() as session:
            record = TaskRecord(
                task_id=task_id,
                task_type=task_type,
                task_name=task_name,
                uid=uid,
                source=source,
                status="pending",
                progress=max(0, min(100, int(progress))),
                message=message,
                payload=payload,
                task_log=task_log,
                parent_task_id=parent_task_id,
                retry_count=retry_count,
                scheduler_job_id=scheduler_job_id,
                dedupe_key=dedupe_key,
                trigger_source=trigger_source,
                triggered_by_uid=triggered_by_uid,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                existing = self.get_active_by_dedupe_key(dedupe_key) if dedupe_key else self.get_by_task_id(task_id)
                if existing is None:
                    existing = self.ensure_record(
                        task_id=task_id,
                        task_type=task_type,
                        source=source,
                        status="pending",
                        task_name=task_name,
                        uid=uid,
                        payload=payload,
                        message=message,
                        progress=progress,
                        task_log=task_log,
                        parent_task_id=parent_task_id,
                        retry_count=retry_count,
                        scheduler_job_id=scheduler_job_id,
                        dedupe_key=dedupe_key,
                        trigger_source=trigger_source,
                        triggered_by_uid=triggered_by_uid,
                    )
                    return existing, True
                return existing, False
            return self._detach(session, record), True

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
        dedupe_key: Optional[str] = None,
        trigger_source: Optional[str] = None,
        triggered_by_uid: Optional[int] = None,
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
                    progress=0 if progress is None else max(0, min(100, int(progress))),
                    message=message,
                    payload=payload,
                    result=result,
                    error=error,
                    task_log=task_log,
                    started_at=started_at,
                    finished_at=finished_at,
                    parent_task_id=parent_task_id,
                    retry_count=0 if retry_count is None else retry_count,
                    scheduler_job_id=scheduler_job_id,
                    dedupe_key=dedupe_key,
                    trigger_source=trigger_source,
                    triggered_by_uid=triggered_by_uid,
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
                        dedupe_key=dedupe_key,
                        trigger_source=trigger_source,
                        triggered_by_uid=triggered_by_uid,
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
                dedupe_key=dedupe_key,
                trigger_source=trigger_source,
                triggered_by_uid=triggered_by_uid,
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

    def get_active_by_dedupe_key(self, dedupe_key: Optional[str]) -> Optional[TaskRecord]:
        if not dedupe_key:
            return None
        with self.db.get_session() as session:
            record = session.execute(
                select(TaskRecord)
                .where(
                    TaskRecord.dedupe_key == dedupe_key,
                    TaskRecord.status.in_(self.ACTIVE_STATUSES),
                )
                .order_by(desc(TaskRecord.created_at))
                .limit(1)
            ).scalar_one_or_none()
            return self._detach(session, record) if record is not None else None

    def get_active_by_scheduler_job_id(self, scheduler_job_id: str) -> Optional[TaskRecord]:
        with self.db.get_session() as session:
            record = session.execute(
                select(TaskRecord)
                .where(
                    TaskRecord.scheduler_job_id == scheduler_job_id,
                    TaskRecord.status.in_(self.ACTIVE_STATUSES),
                )
                .order_by(desc(TaskRecord.created_at))
                .limit(1)
            ).scalar_one_or_none()
            return self._detach(session, record) if record is not None else None

    def get_latest_by_scheduler_job_ids(self, scheduler_job_ids: Iterable[str]) -> Dict[str, TaskRecord]:
        job_ids = [str(job_id) for job_id in scheduler_job_ids if str(job_id)]
        if not job_ids:
            return {}
        with self.db.get_session() as session:
            rows = session.execute(
                select(TaskRecord)
                .where(TaskRecord.scheduler_job_id.in_(job_ids))
                .order_by(TaskRecord.scheduler_job_id.asc(), desc(TaskRecord.created_at))
            ).scalars().all()
            latest: Dict[str, TaskRecord] = {}
            for row in rows:
                if row.scheduler_job_id in latest:
                    continue
                latest[row.scheduler_job_id] = self._detach(session, row)
            return latest

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

    def list_tasks(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        statuses: Optional[Iterable[str]] = None,
        uid: Optional[int] = None,
        task_type: Optional[str] = None,
        source: Optional[str] = None,
        trigger_source: Optional[str] = None,
        scheduler_job_id: Optional[str] = None,
        keyword: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        started_from: Optional[datetime] = None,
        started_to: Optional[datetime] = None,
    ) -> List[TaskRecord]:
        with self.db.get_session() as session:
            query = select(TaskRecord)
            conditions = self._build_filters(
                statuses=statuses,
                uid=uid,
                task_type=task_type,
                source=source,
                trigger_source=trigger_source,
                scheduler_job_id=scheduler_job_id,
                keyword=keyword,
                created_from=created_from,
                created_to=created_to,
                started_from=started_from,
                started_to=started_to,
            )
            if conditions:
                query = query.where(*conditions)
            rows = session.execute(
                query.order_by(desc(TaskRecord.created_at)).offset(max(0, offset)).limit(max(1, limit))
            ).scalars().all()
            return [self._detach(session, row) for row in rows]

    def count_tasks(
        self,
        *,
        statuses: Optional[Iterable[str]] = None,
        uid: Optional[int] = None,
        task_type: Optional[str] = None,
        source: Optional[str] = None,
        trigger_source: Optional[str] = None,
        scheduler_job_id: Optional[str] = None,
        keyword: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        started_from: Optional[datetime] = None,
        started_to: Optional[datetime] = None,
    ) -> int:
        with self.db.get_session() as session:
            query = select(func.count()).select_from(TaskRecord)
            conditions = self._build_filters(
                statuses=statuses,
                uid=uid,
                task_type=task_type,
                source=source,
                trigger_source=trigger_source,
                scheduler_job_id=scheduler_job_id,
                keyword=keyword,
                created_from=created_from,
                created_to=created_to,
                started_from=started_from,
                started_to=started_to,
            )
            if conditions:
                query = query.where(*conditions)
            return int(session.execute(query).scalar_one() or 0)

    def count_by_status(
        self,
        *,
        uid: Optional[int] = None,
        task_type: Optional[str] = None,
        source: Optional[str] = None,
        trigger_source: Optional[str] = None,
        scheduler_job_id: Optional[str] = None,
        keyword: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        started_from: Optional[datetime] = None,
        started_to: Optional[datetime] = None,
    ) -> Dict[str, int]:
        with self.db.get_session() as session:
            query = select(TaskRecord.status, func.count()).group_by(TaskRecord.status)
            conditions = self._build_filters(
                statuses=None,
                uid=uid,
                task_type=task_type,
                source=source,
                trigger_source=trigger_source,
                scheduler_job_id=scheduler_job_id,
                keyword=keyword,
                created_from=created_from,
                created_to=created_to,
                started_from=started_from,
                started_to=started_to,
            )
            if conditions:
                query = query.where(*conditions)
            return {str(status): int(count or 0) for status, count in session.execute(query).all()}

    @staticmethod
    def to_dict(record: TaskRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "task_id": record.task_id,
            "task_type": record.task_type,
            "task_name": record.task_name,
            "uid": record.uid,
            "source": record.source,
            "trigger_source": record.trigger_source,
            "triggered_by_uid": record.triggered_by_uid,
            "status": record.status,
            "progress": record.progress,
            "message": record.message,
            "payload": record.payload,
            "result": record.result,
            "error": record.error,
            "task_log": record.task_log,
            "parent_task_id": record.parent_task_id,
            "dedupe_key": record.dedupe_key,
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

    @staticmethod
    def _build_filters(
        *,
        statuses: Optional[Iterable[str]],
        uid: Optional[int],
        task_type: Optional[str],
        source: Optional[str],
        trigger_source: Optional[str],
        scheduler_job_id: Optional[str],
        keyword: Optional[str],
        created_from: Optional[datetime],
        created_to: Optional[datetime],
        started_from: Optional[datetime],
        started_to: Optional[datetime],
    ) -> List[Any]:
        conditions: List[Any] = []
        status_list = [str(status).strip().lower() for status in statuses or [] if str(status).strip()]
        if status_list:
            conditions.append(TaskRecord.status.in_(status_list))
        if uid is not None:
            conditions.append(TaskRecord.uid == uid)
        if task_type:
            conditions.append(TaskRecord.task_type == task_type)
        if source:
            conditions.append(TaskRecord.source == source)
        if trigger_source:
            conditions.append(TaskRecord.trigger_source == trigger_source)
        if scheduler_job_id:
            conditions.append(TaskRecord.scheduler_job_id == scheduler_job_id)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    TaskRecord.task_id.ilike(pattern),
                    TaskRecord.task_name.ilike(pattern),
                    TaskRecord.task_type.ilike(pattern),
                    TaskRecord.message.ilike(pattern),
                    TaskRecord.scheduler_job_id.ilike(pattern),
                )
            )
        if created_from is not None:
            conditions.append(TaskRecord.created_at >= created_from)
        if created_to is not None:
            conditions.append(TaskRecord.created_at <= created_to)
        if started_from is not None:
            conditions.append(TaskRecord.started_at >= started_from)
        if started_to is not None:
            conditions.append(TaskRecord.started_at <= started_to)
        return conditions

# -*- coding: utf-8 -*-
"""Task execution record ORM model."""

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from src.db.base import Base
from src.time_utils import utc_now


class TaskRecord(Base):
    """Persistent record for one background task execution instance."""

    __tablename__ = "task"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False)
    task_type = Column(String(64), nullable=False, index=True)
    task_name = Column(String(128), nullable=True)
    uid = Column(Integer, nullable=True, index=True)
    source = Column(String(32), nullable=False, index=True)
    trigger_source = Column(String(32), nullable=True, index=True)
    triggered_by_uid = Column(Integer, nullable=True, index=True)
    status = Column(String(24), nullable=False, index=True)
    progress = Column(Integer, nullable=False, default=0)
    message = Column(String(255), nullable=True)
    payload = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    task_log = Column(String(255), nullable=True)
    parent_task_id = Column(String(64), nullable=True, index=True)
    dedupe_key = Column(String(160), nullable=True, index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    scheduler_job_id = Column(String(96), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("task_id", name="uix_task_task_id"),
        Index("ix_task_type_created_at", "task_type", "created_at"),
        Index("ix_task_status_created_at", "status", "created_at"),
        Index("ix_task_uid_created_at", "uid", "created_at"),
        Index("ix_task_dedupe_status", "dedupe_key", "status"),
    )

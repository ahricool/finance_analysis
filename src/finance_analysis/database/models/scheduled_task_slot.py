"""Persistent idempotency records for scheduled intraday task slots."""

from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class ScheduledTaskSlot(Base):
    """Record one successfully processed scheduler slot.

    This table is business idempotency state, not an execution mutex. Running
    task exclusion is handled separately by PostgreSQL advisory locks.
    """

    __tablename__ = "scheduled_task_slot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(96), nullable=False)
    trading_date = Column(Date, nullable=False)
    scheduled_slot = Column(DateTime(timezone=True), nullable=False)
    task_id = Column(String(64), nullable=False)
    completed_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "trading_date",
            "scheduled_slot",
            name="uix_scheduled_task_slot_identity",
        ),
    )

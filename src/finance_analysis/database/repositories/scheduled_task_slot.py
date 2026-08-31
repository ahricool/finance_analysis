"""Persistence for successful scheduled intraday slots."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.scheduled_task_slot import ScheduledTaskSlot
from finance_analysis.database.session import DatabaseManager


class ScheduledTaskSlotRepository:
    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def was_completed(self, *, job_id: str, trading_date: date, scheduled_slot: datetime) -> bool:
        with self.db.get_session() as session:
            return session.execute(
                select(ScheduledTaskSlot.id).where(
                    ScheduledTaskSlot.job_id == job_id,
                    ScheduledTaskSlot.trading_date == trading_date,
                    ScheduledTaskSlot.scheduled_slot == scheduled_slot,
                )
            ).scalar_one_or_none() is not None

    def record_completed(
        self,
        *,
        job_id: str,
        trading_date: date,
        scheduled_slot: datetime,
        task_id: str,
    ) -> bool:
        """Persist a successful slot, returning False if it was already recorded."""

        try:
            with self.db.session_scope() as session:
                session.add(
                    ScheduledTaskSlot(
                        job_id=job_id,
                        trading_date=trading_date,
                        scheduled_slot=scheduled_slot,
                        task_id=task_id,
                        completed_at=utc_now(),
                    )
                )
                session.flush()
            return True
        except IntegrityError:
            return False

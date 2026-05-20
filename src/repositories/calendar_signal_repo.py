# -*- coding: utf-8 -*-
"""Repository for calendar_signals CRUD operations."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage import CalendarSignal, DatabaseManager


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


class CalendarSignalRepo:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db()

    def list_by_date(self, signal_date: date) -> List[CalendarSignal]:
        with self.db.get_session() as session:
            return session.execute(
                select(CalendarSignal)
                .where(CalendarSignal.signal_date == signal_date)
                .order_by(CalendarSignal.created_at.desc())
            ).scalars().all()

    def create(
        self,
        signal_date: date,
        title: str,
        content: Optional[str] = None,
        signal_type: Optional[str] = None,
    ) -> CalendarSignal:
        item = CalendarSignal(
            signal_date=signal_date,
            title=title.strip(),
            content=(content or '').strip() or None,
            signal_type=(signal_type or '').strip() or None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        def _write(session: Session) -> CalendarSignal:
            session.add(item)
            session.flush()
            session.refresh(item)
            return item

        return self.db._run_write_transaction('calendar_signals.create', _write)

    def update(
        self,
        item_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        signal_type: Optional[str] = None,
    ) -> Optional[CalendarSignal]:
        def _write(session: Session) -> Optional[CalendarSignal]:
            obj = session.get(CalendarSignal, item_id)
            if obj is None:
                return None
            if title is not None:
                obj.title = title.strip()
            if content is not None:
                obj.content = content.strip() or None
            if signal_type is not None:
                obj.signal_type = signal_type.strip() or None
            obj.updated_at = datetime.now()
            session.flush()
            session.refresh(obj)
            return obj

        return self.db._run_write_transaction('calendar_signals.update', _write)

    def delete(self, item_id: int) -> bool:
        def _write(session: Session) -> bool:
            obj = session.get(CalendarSignal, item_id)
            if obj is None:
                return False
            session.delete(obj)
            return True

        return self.db._run_write_transaction('calendar_signals.delete', _write)

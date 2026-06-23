# -*- coding: utf-8 -*-
"""Repository for calendar CRUD operations."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from finance_analysis.database.base import ensure_aware_datetime
from finance_analysis.database.session import DatabaseManager
from finance_analysis.database.models import CalendarEntry
from finance_analysis.core.time import utc_now
from finance_analysis.core.time import day_bounds_utc


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


class CalendarRepo:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db()

    def list_by_date(
        self,
        day: date,
        timezone_name: str = "Asia/Shanghai",
        uid: Optional[int] = None,
    ) -> List[CalendarEntry]:
        start, end = day_bounds_utc(day, timezone_name)
        with self.db.get_session() as session:
            stmt = (
                select(CalendarEntry)
                .where(and_(CalendarEntry.time >= start, CalendarEntry.time < end))
                .order_by(CalendarEntry.time.desc(), CalendarEntry.created_at.desc())
            )
            if uid is not None:
                stmt = stmt.where(CalendarEntry.uid == uid)
            return session.execute(stmt).scalars().all()

    def get_by_type_and_date(
        self,
        *,
        type: str,
        day: date,
        timezone_name: str = "Asia/Shanghai",
        uid: Optional[int] = None,
    ) -> Optional[CalendarEntry]:
        """Return the latest calendar entry matching a business type on a local date."""
        start, end = day_bounds_utc(day, timezone_name)
        normalized_type = (type or '').strip()
        with self.db.get_session() as session:
            stmt = (
                select(CalendarEntry)
                .where(
                    CalendarEntry.type == normalized_type,
                    CalendarEntry.time >= start,
                    CalendarEntry.time < end,
                )
                .order_by(CalendarEntry.updated_at.desc(), CalendarEntry.created_at.desc())
            )
            if uid is not None:
                stmt = stmt.where(CalendarEntry.uid == uid)
            return session.execute(stmt).scalars().first()

    def create(
        self,
        *,
        uid: int,
        time: datetime,
        title: str,
        content: Optional[str] = None,
        type: Optional[str] = None,
    ) -> CalendarEntry:
        now = utc_now()
        item = CalendarEntry(
            uid=uid,
            time=ensure_aware_datetime(time) or now,
            title=title.strip(),
            content=(content or '').strip() or None,
            type=(type or '').strip() or None,
            created_at=now,
            updated_at=now,
        )

        def _write(session: Session) -> CalendarEntry:
            session.add(item)
            session.flush()
            session.refresh(item)
            return item

        return self.db._run_write_transaction('calendar.create', _write)

    def update(
        self,
        item_id: int,
        *,
        uid: Optional[int] = None,
        title: Optional[str] = None,
        content: Optional[str] = None,
        type: Optional[str] = None,
    ) -> Optional[CalendarEntry]:
        def _write(session: Session) -> Optional[CalendarEntry]:
            obj = session.get(CalendarEntry, item_id)
            if obj is None:
                return None
            if uid is not None and obj.uid != uid:
                return None
            if title is not None:
                obj.title = title.strip()
            if content is not None:
                obj.content = content.strip() or None
            if type is not None:
                obj.type = type.strip() or None
            obj.updated_at = utc_now()
            session.flush()
            session.refresh(obj)
            return obj

        return self.db._run_write_transaction('calendar.update', _write)

    def delete(self, item_id: int, uid: Optional[int] = None) -> bool:
        def _write(session: Session) -> bool:
            obj = session.get(CalendarEntry, item_id)
            if obj is None:
                return False
            if uid is not None and obj.uid != uid:
                return False
            session.delete(obj)
            return True

        return self.db._run_write_transaction('calendar.delete', _write)

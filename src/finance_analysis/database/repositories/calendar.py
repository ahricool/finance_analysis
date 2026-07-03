# -*- coding: utf-8 -*-
"""Repository for calendar CRUD operations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from finance_analysis.database.base import ensure_aware_datetime
from finance_analysis.database.session import DatabaseManager
from finance_analysis.database.models import CalendarEntry
from finance_analysis.core.time import (
    coerce_aware_utc,
    date_range_bounds_utc,
    day_bounds_utc,
    utc_now,
    validate_display_timezone,
)


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


A_SHARE_CALENDAR_TYPES = frozenset(
    {
        "scheduled_a_share_intraday",
        "a_share_intraday_signal",
        "scheduled_signal_evaluation_cn",
    }
)
US_CALENDAR_TYPES = frozenset(
    {
        "scheduled_us_premarket",
        "scheduled_us_intraday",
        "us_intraday_signal",
        "scheduled_us_postmarket_review",
        "scheduled_signal_evaluation_us",
    }
)
NEWS_CALENDAR_TYPES = frozenset({"scheduled_us_premarket_news"})
KNOWN_CALENDAR_TYPES = A_SHARE_CALENDAR_TYPES | US_CALENDAR_TYPES | NEWS_CALENDAR_TYPES


def calendar_category_condition(category: str):
    """Return the SQL filter for one user-facing calendar section."""
    if category == "a_share":
        return CalendarEntry.type.in_(A_SHARE_CALENDAR_TYPES)
    if category == "us":
        return CalendarEntry.type.in_(US_CALENDAR_TYPES)
    if category == "news":
        return CalendarEntry.type.in_(NEWS_CALENDAR_TYPES)
    if category == "other":
        return or_(CalendarEntry.type.is_(None), CalendarEntry.type.notin_(KNOWN_CALENDAR_TYPES))
    raise ValueError(f"unknown calendar category: {category}")


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

    def list_by_date_paginated(
        self,
        day: date,
        *,
        timezone_name: str = "Asia/Shanghai",
        uid: Optional[int] = None,
        category: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[List[CalendarEntry], int]:
        start, end = day_bounds_utc(day, timezone_name)
        conditions = [CalendarEntry.time >= start, CalendarEntry.time < end]
        if uid is not None:
            conditions.append(CalendarEntry.uid == uid)
        if category is not None:
            conditions.append(calendar_category_condition(category))

        with self.db.get_session() as session:
            total = int(
                session.execute(
                    select(func.count()).select_from(CalendarEntry).where(and_(*conditions))
                ).scalar_one()
                or 0
            )
            stmt = (
                select(CalendarEntry)
                .where(and_(*conditions))
                .order_by(CalendarEntry.time.desc(), CalendarEntry.created_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
            items = session.execute(stmt).scalars().all()
            return list(items), total

    def count_by_date_range(
        self,
        start: date,
        end: date,
        timezone_name: str = "Asia/Shanghai",
        uid: Optional[int] = None,
    ) -> Dict[date, int]:
        timezone_name = validate_display_timezone(timezone_name)
        start_dt, end_dt = date_range_bounds_utc(start, end, timezone_name)
        tz = ZoneInfo(timezone_name)
        counts = {start + timedelta(days=offset): 0 for offset in range((end - start).days + 1)}
        with self.db.get_session() as session:
            stmt = select(CalendarEntry.time).where(
                and_(CalendarEntry.time >= start_dt, CalendarEntry.time < end_dt)
            )
            if uid is not None:
                stmt = stmt.where(CalendarEntry.uid == uid)
            for (entry_time,) in session.execute(stmt).all():
                local_day = coerce_aware_utc(entry_time).astimezone(tz).date()
                if local_day in counts:
                    counts[local_day] += 1
        return counts

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

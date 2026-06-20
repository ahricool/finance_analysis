# -*- coding: utf-8 -*-
"""Calendar ORM model."""

from sqlalchemy import Column, DateTime, Integer, String, Text

from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now


class CalendarEntry(Base):
    """日历记录 — 按具体时间记录自动化任务结果。"""

    __tablename__ = 'calendar'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    time = Column(DateTime(timezone=True), nullable=False, index=True)
    title = Column(String(120), nullable=False)
    content = Column(Text, nullable=True)
    type = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

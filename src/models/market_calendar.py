# -*- coding: utf-8 -*-
"""Market finance calendar ORM models."""

from sqlalchemy import Column, Date, DateTime, Integer, String, Text, UniqueConstraint

from src.db.base import Base
from src.time_utils import utc_now


class FinanceEvent(Base):
    """Structured market calendar event fetched from an external provider."""

    __tablename__ = "finance_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, index=True)
    provider_event_id = Column(String(128), nullable=True, index=True)
    event_key = Column(String(96), nullable=False, index=True)
    calendar_type = Column(String(32), nullable=False, index=True)
    market = Column(String(16), nullable=False, index=True)
    symbol = Column(String(32), nullable=True, index=True)
    counter_name = Column(String(128), nullable=True)
    event_type = Column(String(64), nullable=True)
    activity_type = Column(String(64), nullable=True)
    event_date = Column(Date, nullable=False, index=True)
    event_datetime = Column(DateTime(timezone=True), nullable=True, index=True)
    date_type = Column(String(32), nullable=True)
    financial_market_time = Column(String(64), nullable=True)
    title = Column(String(120), nullable=False)
    content = Column(Text, nullable=False)
    star = Column(Integer, nullable=True, index=True)
    currency = Column(String(16), nullable=True)
    data_kv_json = Column(Text, nullable=True)
    raw_payload_json = Column(Text, nullable=True)
    first_seen_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    notified_at = Column(DateTime(timezone=True), nullable=True)
    notification_fingerprint = Column(String(96), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("event_key", name="uix_finance_events_event_key"),
    )

# -*- coding: utf-8 -*-
"""Market finance calendar ORM models."""

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Float, Integer, String, Text, UniqueConstraint

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


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
    event_date = Column(Date, nullable=False, index=True)
    event_datetime = Column(DateTime(timezone=True), nullable=True, index=True)
    market_session = Column(String(64), nullable=True)
    reporting_period = Column(String(64), nullable=True)
    eps_estimate = Column(Float, nullable=True)
    reported_eps = Column(Float, nullable=True)
    eps_surprise_pct = Column(Float, nullable=True)
    title = Column(String(120), nullable=False)
    content = Column(Text, nullable=False)
    currency = Column(String(16), nullable=True)
    raw_payload_json = Column(Text, nullable=True)
    importance_score = Column(Integer, nullable=True, index=True)
    importance_reason = Column(Text, nullable=True)
    importance_confidence = Column(Float, nullable=True)
    importance_model = Column(String(128), nullable=True)
    importance_prompt_version = Column(String(32), nullable=True)
    importance_input_hash = Column(String(64), nullable=True, index=True)
    importance_scored_at = Column(DateTime(timezone=True), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        CheckConstraint("calendar_type IN ('earnings', 'macro')", name="ck_finance_events_type"),
        CheckConstraint(
            "(calendar_type = 'macro' AND market = 'US' AND symbol IS NULL) OR "
            "(calendar_type = 'earnings' AND market IN ('US', 'CN') AND symbol IS NOT NULL)",
            name="ck_finance_events_scope",
        ),
        UniqueConstraint("event_key", name="uix_finance_events_event_key"),
    )

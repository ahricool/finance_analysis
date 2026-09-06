"""Durable investment reports and user-owned notes."""

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class TimelineEntry(Base):
    __tablename__ = "timeline_entries"

    id = Column(Integer, primary_key=True)
    uid = Column(Integer, nullable=False, index=True)
    entry_type = Column(String(32), nullable=False, index=True)
    market = Column(String(16), nullable=True, index=True)
    event_time = Column(DateTime(timezone=True), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    summary = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    importance = Column(String(16), nullable=False, default="normal", index=True)
    actionability = Column(String(24), nullable=False, default="none", index=True)
    symbol = Column(String(32))
    related_symbols = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list)
    source_task = Column(String(128))
    source_run_id = Column(String(64), index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('a_share_pre_close','us_premarket','us_postmarket','manual_note')", name="ck_timeline_type"
        ),
        CheckConstraint("importance IN ('low','normal','high','critical')", name="ck_timeline_importance"),
        CheckConstraint("actionability IN ('none','watch','consider','action_required')", name="ck_timeline_action"),
    )

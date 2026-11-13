"""Only catalog and associations persist. No market/outcome/price payloads."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now

J = JSONB().with_variant(JSON(), "sqlite")


class PredictionTag(Base):
    __tablename__ = "prediction_tag"
    id = Column(Integer, primary_key=True)
    provider = Column(String(20), nullable=False, default="polymarket")
    tag_id = Column(String(80), nullable=False)
    slug = Column(String(255), nullable=False)
    label = Column(Text, nullable=False)
    visible = Column(Boolean, nullable=False, default=False)
    rule_group = Column(String(32), nullable=False)
    manual_visible = Column(Boolean)
    synced_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("provider", "tag_id", name="uq_prediction_tag_provider"),)


class PredictionEvent(Base):
    __tablename__ = "prediction_event"
    id = Column(Integer, primary_key=True)
    provider = Column(String(20), nullable=False, default="polymarket")
    event_id = Column(String(80), nullable=False)
    slug = Column(String(512), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    tag_ids = Column(J, nullable=False, default=list)
    start_at = Column(DateTime(timezone=True))
    end_at = Column(DateTime(timezone=True))
    closed = Column(Boolean)
    archived = Column(Boolean)
    retained = Column(Boolean, nullable=False, default=True)
    rule_retained = Column(Boolean, nullable=False, default=True)
    rule_reason = Column(String(80), nullable=False)
    rule_version = Column(String(32), nullable=False)
    manual_retained = Column(Boolean)
    semantic_hash = Column(String(64), nullable=False)
    match_status = Column(String(24), nullable=False, default="pending")
    # Per-public-security progress; never contains watched-by identity or private holdings.
    match_progress = Column(J, nullable=False, default=dict)
    match_version = Column(String(64))
    retry_at = Column(DateTime(timezone=True))
    retry_count = Column(Integer, nullable=False, default=0)
    match_error = Column(String(200))
    synced_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_prediction_event_provider"),
        Index("ix_prediction_event_list", "retained", "closed", "synced_at"),
    )


class PredictionInstrumentLink(Base):
    __tablename__ = "prediction_instrument_link"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("prediction_event.id", ondelete="CASCADE"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String(16), nullable=False)
    relevance = Column(String(16), nullable=False)
    reason = Column(Text, nullable=False)
    source = Column(String(16), nullable=False, default="automatic")
    blocked = Column(Boolean, nullable=False, default=False)
    input_version = Column(String(64), nullable=False)
    judged_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("event_id", "instrument_id", name="uq_prediction_link"),)

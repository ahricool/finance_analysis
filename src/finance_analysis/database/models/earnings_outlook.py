"""Immutable successful research/predictions; mutable execution state and separate actuals."""

from sqlalchemy import Column, Integer, String, DateTime, Date, JSON, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now

JT = JSONB().with_variant(JSON(), "sqlite")


class EarningsResearch(Base):
    __tablename__ = "earnings_research"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("finance_events.id"), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False)
    cache_key = Column(String(64), nullable=False, index=True)
    bundle = Column(JT, nullable=False)
    search_evidence = Column(JT, nullable=False)
    model = Column(String(160))
    backend = Column(String(32))
    prompt_version = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    data_cutoff = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class EarningsPrediction(Base):
    __tablename__ = "earnings_prediction"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("finance_events.id"), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False)
    research_id = Column(Integer, ForeignKey("earnings_research.id"), nullable=False)
    schedule_hash = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    stage = Column(String(16), nullable=False)
    context = Column(JT, nullable=False)
    prediction = Column(JT, nullable=False)
    model = Column(String(160))
    backend = Column(String(32))
    prompt_version = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    data_cutoff = Column(DateTime(timezone=True), nullable=False)
    release_cutoff = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    target_trading_date = Column(Date, nullable=False)
    __table_args__ = (UniqueConstraint("event_id", "stage", "input_hash", name="uq_earnings_prediction_input"),)


class EarningsOutlookState(Base):
    __tablename__ = "earnings_outlook_state"
    event_id = Column(Integer, ForeignKey("finance_events.id"), primary_key=True)
    status = Column(String(24), nullable=False)
    error = Column(Text)
    latest_prediction_id = Column(Integer, ForeignKey("earnings_prediction.id"))
    # Small read projection, deliberately excludes research, scenarios and full input.
    summary = Column(JT, nullable=False, default=dict)
    schedule_hash = Column(String(64))
    frozen_schedule_hash = Column(String(64))
    actual = Column(JT)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

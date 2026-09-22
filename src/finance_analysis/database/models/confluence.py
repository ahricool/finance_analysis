"""Confluence evidence plus a generation manifest, including empty generations."""

from sqlalchemy import Column, Integer, String, Date, DateTime, Float, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy import CheckConstraint, JSON
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now

JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class ConfluenceRun(Base):
    __tablename__ = "confluence_run"
    market = Column(String(8), primary_key=True)
    trade_date = Column(Date, primary_key=True)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    algorithm_version = Column(String(32), nullable=False)
    source_availability = Column(JSON_TYPE, nullable=False)
    __table_args__ = (CheckConstraint("market IN ('CN','US')", name="ck_confluence_run_market"),)


class ConfluenceSnapshot(Base):
    __tablename__ = "confluence_snapshot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    instrument_id = Column(Integer, ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False)
    confluence_score = Column(Float)
    available_weight = Column(Integer, nullable=False)
    available_signal_count = Column(Integer, nullable=False)
    positive_signal_count = Column(Integer, nullable=False)
    eligible = Column(Boolean, nullable=False)
    strong_confluence = Column(Boolean, nullable=False)
    signals = Column(JSON_TYPE, nullable=False)
    reasons = Column(JSON_TYPE, nullable=False)
    algorithm_version = Column(String(32), nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("market", "trade_date", "instrument_id", name="uix_confluence_market_date_instrument"),
        CheckConstraint("market IN ('CN','US')", name="ck_confluence_market"),
        CheckConstraint("confluence_score IS NULL OR confluence_score BETWEEN 0 AND 100", name="ck_confluence_score"),
        CheckConstraint(
            "positive_signal_count <= available_signal_count AND available_signal_count BETWEEN 0 AND 5",
            name="ck_confluence_counts",
        ),
    )

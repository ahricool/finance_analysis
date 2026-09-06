"""Structured model judgments, separate from source news facts."""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class NewsAnalysis(Base):
    __tablename__ = "news_analysis"

    id = Column(Integer, primary_key=True)
    news_intel_id = Column(Integer, ForeignKey("news_intel.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_type = Column(String(32), nullable=False)
    importance_score = Column(Integer, nullable=False)
    importance_reason = Column(Text)
    event_type = Column(String(64))
    time_sensitivity = Column(String(32))
    importance_confidence = Column(Float)
    impact = Column(String(32))
    impact_score = Column(Integer)
    impact_reason = Column(Text)
    impact_confidence = Column(Float)
    related_symbols = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list)
    watch_points = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list)
    risk_notes = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list)
    importance = Column(String(16), nullable=False)
    actionability = Column(String(24), nullable=False)
    model = Column(String(128))
    prompt_version = Column(String(64), nullable=False)
    analyzed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("news_intel_id", "analysis_type", name="uq_news_analysis_type"),
        CheckConstraint("importance_score BETWEEN 0 AND 10", name="ck_news_importance_score"),
        CheckConstraint("importance IN ('low','normal','high','critical')", name="ck_news_importance"),
        CheckConstraint("actionability IN ('none','watch','consider','action_required')", name="ck_news_action"),
    )

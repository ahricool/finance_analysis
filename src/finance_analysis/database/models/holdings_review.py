"""Private, frozen pre-close portfolio reviews; one result per user/market/session."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class HoldingsReview(Base):
    __tablename__ = "holdings_review"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, ForeignKey("users.id"), nullable=False)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    status = Column(String(16), nullable=False)
    input_snapshot = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    decision = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    markdown = Column(Text, nullable=True)
    search_evidence = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    notification_id = Column(Integer, ForeignKey("notification.id", ondelete="SET NULL"), nullable=True)
    error = Column(String(500), nullable=True)
    model = Column(String(160), nullable=True)
    backend = Column(String(32), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("uid", "market", "trade_date", name="uix_holdings_review_scope"),
        CheckConstraint("market IN ('CN','US')", name="ck_holdings_review_market"),
        CheckConstraint("status IN ('processing','completed','failed')", name="ck_holdings_review_status"),
        Index("ix_holdings_review_uid_market_date", "uid", "market", "trade_date"),
    )

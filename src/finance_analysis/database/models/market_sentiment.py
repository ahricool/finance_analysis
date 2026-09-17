"""One source generation and one derived aggregate per close, with no instrument FK."""

from sqlalchemy import Column, Date, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.database.base import Base


class MarketSentimentSourceSnapshot(Base):
    __tablename__ = "market_sentiment_source_snapshot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    source_kind = Column(String(16), nullable=False)
    requested_trade_date = Column(Date)
    source_timestamp = Column(DateTime(timezone=True), nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    total = Column(Integer, nullable=False)
    item_count = Column(Integer, nullable=False)
    payload = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    quality = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    __table_args__ = (UniqueConstraint("trade_date", "source_kind", name="uix_sentiment_source_date_kind"),)


class MarketSentimentSnapshot(Base):
    __tablename__ = "market_sentiment_snapshot"
    trade_date = Column(Date, primary_key=True)
    rule_version = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)

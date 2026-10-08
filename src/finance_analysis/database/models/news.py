# -*- coding: utf-8 -*-
"""News and fundamental context ORM models."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now


class NewsIntel(Base):
    """One original news fact per URL; all usage belongs to NewsIntelUsage."""
    __tablename__ = "news_intel"
    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    snippet = Column(Text)
    url = Column(String(1000), nullable=False)
    source = Column(String(100))
    published_date = Column(DateTime(timezone=True), index=True)
    provider = Column(String(32), index=True)
    # First insertion of this URL, never updated by repeated observations.
    fetched_at = Column(DateTime(timezone=True), default=utc_now, index=True)
    __table_args__ = (UniqueConstraint("url", name="uix_news_url"),)


class NewsIntelUsage(Base):
    """A query's observation of a news fact for a symbol and purpose."""

    __tablename__ = "news_intel_usage"
    id = Column(Integer, primary_key=True)
    news_intel_id = Column(Integer, ForeignKey("news_intel.id", ondelete="CASCADE"), nullable=False, index=True)
    usage_type = Column(String(32), nullable=False, index=True)
    query_id = Column(String(64), nullable=False, default="", index=True)
    symbol = Column(String(32), nullable=False, index=True)
    uid = Column(Integer, index=True)
    # Latest observation for this usage key; refreshed on conflict.
    observed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("news_intel_id", "usage_type", "query_id", "symbol", name="uq_news_usage"),)


class FundamentalSnapshot(Base):
    """
    基本面上下文快照（P0 write-only）。

    仅用于写入，主链路不依赖读取该表，便于后续回测/画像扩展。
    """
    __tablename__ = 'fundamental_snapshot'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=True, index=True)
    query_id = Column(String(64), nullable=False, index=True)
    code = Column(String(10), nullable=False, index=True)
    payload = Column(Text, nullable=False)
    source_chain = Column(Text)
    coverage = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    __table_args__ = (
        Index('ix_fundamental_snapshot_query_code', 'query_id', 'code'),
        Index('ix_fundamental_snapshot_created', 'created_at'),
    )

    def __repr__(self) -> str:
        return f"<FundamentalSnapshot(query_id={self.query_id}, code={self.code})>"

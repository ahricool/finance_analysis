# -*- coding: utf-8 -*-
"""Watch-list ORM model."""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now


class WatchListItem(Base):
    """自选股 — 用户关注但未必持有的股票。"""

    __tablename__ = 'watch_list'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    code = Column(String(16), nullable=False, index=True)
    name = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    market_type = Column(String(8), nullable=False, default="CN", index=True)
    is_favorite = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("uid", "market_type", "code", name="uix_watch_list_uid_market_code"),
    )

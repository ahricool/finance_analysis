# -*- coding: utf-8 -*-
"""Watch-list ORM model."""

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now


watch_list_tag_link = Table(
    "watch_list_tag_link", Base.metadata,
    Column("watch_list_id", Integer, ForeignKey("watch_list.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("watch_list_tag.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class WatchListTag(Base):
    """User-owned labels, shared by all watch-list markets."""

    __tablename__ = "watch_list_tag"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    name = Column(String(32), nullable=False)
    name_key = Column(String(96), nullable=False)
    __table_args__ = (
        UniqueConstraint("uid", "name_key", name="uix_watch_list_tag_uid_name_key"),
        CheckConstraint("length(name) BETWEEN 1 AND 32", name="ck_watch_list_tag_name_length"),
    )


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
    tags = relationship(WatchListTag, secondary=watch_list_tag_link, order_by=WatchListTag.id)

    __table_args__ = (
        UniqueConstraint("uid", "market_type", "code", name="uix_watch_list_uid_market_code"),
    )

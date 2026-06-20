# -*- coding: utf-8 -*-
"""User ORM model."""

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB

from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now


class User(Base):
    """Registered web user (multi-tenant identity)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(Text, nullable=True)
    avatar_url = Column(String(512), nullable=True)
    role = Column(String(32), nullable=False)  # admin | user
    extra = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict, server_default=text("'{}'"))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_users_extra", "extra", postgresql_using="gin"),
    )

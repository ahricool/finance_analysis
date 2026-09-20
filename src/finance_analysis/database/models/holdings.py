# -*- coding: utf-8 -*-
"""ORM for Google Sheet holdings source (secondary portfolio input)."""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB  # pragma: allowlist secret
from sqlalchemy import JSON

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.base import Base  # pragma: allowlist secret


class HoldingSource(Base):
    __tablename__ = "holding_source"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, unique=True, index=True)
    spreadsheet_id = Column(String(128), nullable=True)
    accounts_range = Column(String(64), nullable=False, default="Accounts")
    positions_range = Column(String(64), nullable=False, default="Positions")
    schema_version = Column(String(32), nullable=False, default="v1")
    encrypted_credentials = Column(LargeBinary, nullable=True)
    auth_status = Column(String(32), nullable=False, default="NOT_CONFIGURED")
    sync_status = Column(String(32), nullable=False, default="IDLE")
    enabled = Column(Boolean, nullable=False, default=False)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(64), nullable=True)
    published_generation = Column(Integer, nullable=False, default=0)
    content_hash = Column(String(64), nullable=True)
    config_version = Column(Integer, nullable=False, default=1)
    published_snapshot = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    risk_policy = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    policy_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "auth_status IN ('NOT_CONFIGURED','DISCONNECTED','PENDING','CONNECTED',"
            "'CONNECTED_NO_OFFLINE','NEEDS_REAUTH')",
            name="ck_holding_source_auth_status",
        ),
        CheckConstraint(
            "sync_status IN ('IDLE','SYNCING','OK','REJECTED','UNAVAILABLE')",
            name="ck_holding_source_sync_status",
        ),
    )

# -*- coding: utf-8 -*-
"""ORM for Google Sheet holdings source, position risk state, and risk events."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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


class PositionRiskState(Base):
    __tablename__ = "position_risk_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("holding_source.id"), nullable=False, index=True)
    account_id = Column(String(64), nullable=False)
    position_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    canonical_symbol = Column(String(32), nullable=True)
    row_version = Column(Integer, nullable=False, default=1)
    rule_version = Column(String(32), nullable=False, default="v1")
    last_bar_end = Column(DateTime(timezone=True), nullable=True)
    last_quote_as_of = Column(DateTime(timezone=True), nullable=True)
    weak_streak = Column(Integer, nullable=False, default=0)
    recovery_streak = Column(Integer, nullable=False, default=0)
    episode_id = Column(String(64), nullable=True)
    plan_status = Column(String(32), nullable=False, default="NONE")
    plan_action = Column(String(16), nullable=False, default="HOLD")
    plan_revision = Column(Integer, nullable=False, default=0)
    active_plan = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    legs_state = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_id", "account_id", "position_id", name="uix_position_risk_state_identity"),
    )


class RiskEvent(Base):
    __tablename__ = "risk_event"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("holding_source.id"), nullable=False, index=True)
    account_id = Column(String(64), nullable=False)
    position_id = Column(String(64), nullable=False)
    leg_id = Column(String(64), nullable=True)
    event_type = Column(String(64), nullable=False, index=True)
    rule_version = Column(String(32), nullable=False)
    input_version = Column(String(64), nullable=True)
    episode_id = Column(String(64), nullable=True)
    plan_revision = Column(Integer, nullable=True)
    action = Column(String(16), nullable=False)
    trigger_quantity = Column(Numeric(28, 8), nullable=True)
    target_quantity = Column(Numeric(28, 8), nullable=True)
    evidence = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    data_time = Column(DateTime(timezone=True), nullable=True)
    dedupe_key = Column(String(190), nullable=False)
    notification_id = Column(Integer, nullable=True)
    push_status = Column(String(32), nullable=False, default="PENDING")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("uid", "dedupe_key", name="uix_risk_event_uid_dedupe"),
        CheckConstraint(
            "push_status IN ('PENDING','SKIPPED','SENT','FAILED')",
            name="ck_risk_event_push_status",
        ),
    )

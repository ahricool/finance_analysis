# -*- coding: utf-8 -*-
"""ORM for Trade Engine strategy state and signals."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB  # pragma: allowlist secret
from sqlalchemy import JSON

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.base import Base  # pragma: allowlist secret


class TradeStrategyState(Base):
    __tablename__ = "trade_strategy_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    account_id = Column(String(64), nullable=False)
    position_id = Column(String(64), nullable=False)
    strategy_key = Column(String(64), nullable=False)
    strategy_version = Column(String(32), nullable=False)
    state = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    last_evaluated_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("uid", "account_id", "position_id", "strategy_key", name="uix_trade_strategy_state"),
    )


class TradeSignalRow(Base):
    __tablename__ = "trade_signal"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    market = Column(String(8), nullable=True)
    account_id = Column(String(64), nullable=True)
    position_id = Column(String(64), nullable=True)
    symbol = Column(String(32), nullable=True)
    strategy_key = Column(String(64), nullable=False)
    strategy_version = Column(String(32), nullable=False)
    action = Column(String(16), nullable=False)
    suggested_quantity = Column(Numeric(28, 8), nullable=True)
    suggested_target_quantity = Column(Numeric(28, 8), nullable=True)
    reason = Column(Text, nullable=False, default="")
    llm_reason = Column(Text, nullable=True)
    reviewed_by_llm = Column(Boolean, nullable=False, default=False)
    evidence = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    signal_key = Column(String(190), nullable=False)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)
    notification_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("uid", "signal_key", name="uix_trade_signal_uid_key"),)

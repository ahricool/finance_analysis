# -*- coding: utf-8 -*-
"""ORM for DB-authoritative stock/ETF portfolio facts."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.base import Base  # pragma: allowlist secret


class PortfolioAccount(Base):
    __tablename__ = "portfolio_account"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    name = Column(String(64), nullable=False)
    market = Column(String(8), nullable=False)
    cash = Column(Numeric(28, 8), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        CheckConstraint("market IN ('CN','US')", name="ck_portfolio_account_market"),
        CheckConstraint("cash >= 0", name="ck_portfolio_account_cash"),
        UniqueConstraint("uid", "market", "name", name="uix_portfolio_account_uid_market_name"),
    )


class PortfolioPosition(Base):
    __tablename__ = "portfolio_position"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("portfolio_account.id"), nullable=False, index=True)
    market = Column(String(8), nullable=False)
    symbol = Column(String(32), nullable=False)
    asset_type = Column(String(16), nullable=False, default="STOCK")
    quantity = Column(Numeric(28, 8), nullable=False, default=0)
    average_cost = Column(Numeric(28, 8), nullable=False, default=0)
    strategy_key = Column(String(64), nullable=True)
    trade_engine_enabled = Column(Boolean, nullable=False, default=True)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        CheckConstraint("market IN ('CN','US')", name="ck_portfolio_position_market"),
        CheckConstraint("asset_type IN ('STOCK','ETF')", name="ck_portfolio_position_asset"),
        CheckConstraint("quantity >= 0", name="ck_portfolio_position_qty"),
    )


class PositionLot(Base):
    __tablename__ = "position_lot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("portfolio_position.id"), nullable=False, index=True)
    role = Column(String(8), nullable=False)
    entry_price = Column(Numeric(28, 8), nullable=False)
    entry_time = Column(DateTime(timezone=True), nullable=False)
    original_quantity = Column(Numeric(28, 8), nullable=False)
    remaining_quantity = Column(Numeric(28, 8), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("role IN ('CORE','ADDON')", name="ck_position_lot_role"),
        CheckConstraint("remaining_quantity >= 0", name="ck_position_lot_remaining"),
    )


class TradeOperation(Base):
    __tablename__ = "trade_operation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("portfolio_account.id"), nullable=False, index=True)
    position_id = Column(Integer, ForeignKey("portfolio_position.id"), nullable=False, index=True)
    market = Column(String(8), nullable=False)
    symbol = Column(String(32), nullable=False)
    side = Column(String(8), nullable=False)
    quantity = Column(Numeric(28, 8), nullable=False)
    price = Column(Numeric(28, 8), nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    note = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("side IN ('BUY','SELL')", name="ck_trade_operation_side"),
        CheckConstraint("quantity > 0", name="ck_trade_operation_qty"),
        CheckConstraint("price > 0", name="ck_trade_operation_price"),
    )


class CashOperation(Base):
    __tablename__ = "cash_operation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("portfolio_account.id"), nullable=False, index=True)
    type = Column(String(16), nullable=False)
    amount = Column(Numeric(28, 8), nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    note = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("type IN ('DEPOSIT','WITHDRAW')", name="ck_cash_operation_type"),
        CheckConstraint("amount > 0", name="ck_cash_operation_amount"),
    )

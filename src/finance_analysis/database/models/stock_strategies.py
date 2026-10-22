"""Shared research ledger, independent of real user portfolios."""

from sqlalchemy import JSON, CheckConstraint, Column, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base

JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class StockStrategyLaunch(Base):
    __tablename__ = "stock_strategy_launch"
    id = Column(Integer, primary_key=True)
    launch_date = Column(Date, nullable=False)
    universes = Column(JSON_TYPE, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (CheckConstraint("id = 1", name="ck_stock_strategy_launch_singleton"),)


class StockStrategyState(Base):
    __tablename__ = "stock_strategy_state"
    strategy_key = Column(String(64), primary_key=True)
    version = Column(String(16), primary_key=True)
    market = Column(String(8), primary_key=True)
    start_date = Column(Date, nullable=False)
    last_date = Column(Date)
    payload = Column(JSON_TYPE, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (CheckConstraint("market IN ('CN', 'US')", name="ck_stock_strategy_state_market"),)


class StockStrategyDay(Base):
    __tablename__ = "stock_strategy_day"
    strategy_key = Column(String(64), primary_key=True)
    version = Column(String(16), primary_key=True)
    market = Column(String(8), primary_key=True)
    trade_date = Column(Date, primary_key=True)
    nav = Column(Float, nullable=False)
    daily_return = Column(Float, nullable=False)
    total_return = Column(Float, nullable=False)
    cagr = Column(Float)
    benchmark_return = Column(Float)
    max_drawdown = Column(Float, nullable=False)
    drawdown = Column(Float, nullable=False)
    exposure = Column(Float, nullable=False)
    payload = Column(JSON_TYPE, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("market IN ('CN', 'US')", name="ck_stock_strategy_day_market"),
        CheckConstraint("nav > 0", name="ck_stock_strategy_day_nav"),
    )


class StockStrategyRun(Base):
    __tablename__ = "stock_strategy_run"
    strategy_key = Column(String(64), primary_key=True)
    version = Column(String(16), primary_key=True)
    market = Column(String(8), primary_key=True)
    trade_date = Column(Date, primary_key=True)
    status = Column(String(16), nullable=False)
    reason = Column(Text)
    attempts = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("status IN ('success', 'waiting', 'failed')", name="ck_stock_strategy_run_status"),
        CheckConstraint("market IN ('CN', 'US')", name="ck_stock_strategy_run_market"),
    )

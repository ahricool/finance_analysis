"""Persistent, engine-neutral backtest runs, fills, and equity points."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_run"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=False)
    task_id = Column(String(64), nullable=True, unique=True)
    engine = Column(String(24), nullable=False)
    engine_version = Column(String(64), nullable=True)
    engine_config = Column(JSONB, nullable=False, default=dict)
    strategy_key = Column(String(64), nullable=False)
    strategy_name = Column(String(128), nullable=False)
    strategy_version = Column(String(32), nullable=False)
    market = Column(String(8), nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(32), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    initial_cash = Column(Float, nullable=False)
    benchmark_code = Column(String(32), nullable=True)
    parameters = Column(JSONB, nullable=False, default=dict)
    price_mode = Column(String(16), nullable=False, default="raw")
    market_rule_version = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    progress = Column(Integer, nullable=False, default=0)
    summary = Column(JSONB, nullable=False, default=dict)
    warnings = Column(JSONB, nullable=False, default=list)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    symbol = relationship("MarketDataSymbol")
    trades = relationship("BacktestTrade", back_populates="run", cascade="all, delete-orphan")
    equity = relationship("BacktestEquity", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("engine IN ('backtrader', 'rqalpha')", name="ck_backtest_run_engine"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')",
            name="ck_backtest_run_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_backtest_run_progress"),
        CheckConstraint("end_date >= start_date", name="ck_backtest_run_dates"),
        CheckConstraint("initial_cash > 0", name="ck_backtest_run_initial_cash"),
        Index("ix_backtest_run_uid_created_at", "uid", "created_at"),
        Index("ix_backtest_run_engine_created_at", "engine", "created_at"),
        Index("ix_backtest_run_strategy_created_at", "strategy_key", "created_at"),
        Index("ix_backtest_run_status_created_at", "status", "created_at"),
    )


class BacktestTrade(Base):
    __tablename__ = "backtest_trade"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, ForeignKey("backtest_run.id", ondelete="CASCADE"), nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(32), nullable=False)
    engine_order_id = Column(String(128), nullable=True)
    side = Column(String(8), nullable=False)
    signal_date = Column(Date, nullable=False)
    order_date = Column(Date, nullable=False)
    trade_date = Column(Date, nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    gross_amount = Column(Float, nullable=False)
    commission = Column(Float, nullable=False, default=0)
    tax = Column(Float, nullable=False, default=0)
    other_fee = Column(Float, nullable=False, default=0)
    total_fee = Column(Float, nullable=False, default=0)
    cash_after = Column(Float, nullable=False)
    position_after = Column(Float, nullable=False)
    return_pct = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    exit_reason = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    run = relationship("BacktestRun", back_populates="trades")

    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="ck_backtest_trade_side"),
        CheckConstraint("quantity > 0", name="ck_backtest_trade_quantity"),
        Index("ix_backtest_trade_run_date", "run_id", "trade_date"),
        Index("ix_backtest_trade_run_code", "run_id", "code"),
    )


class BacktestEquity(Base):
    __tablename__ = "backtest_equity"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, ForeignKey("backtest_run.id", ondelete="CASCADE"), nullable=False)
    trading_date = Column(Date, nullable=False)
    cash = Column(Float, nullable=False)
    position_value = Column(Float, nullable=False)
    total_equity = Column(Float, nullable=False)
    benchmark_equity = Column(Float, nullable=True)
    daily_return_pct = Column(Float, nullable=False)
    cumulative_return_pct = Column(Float, nullable=False)
    benchmark_return_pct = Column(Float, nullable=True)
    drawdown_pct = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    run = relationship("BacktestRun", back_populates="equity")

    __table_args__ = (
        UniqueConstraint("run_id", "trading_date", name="uix_backtest_equity_run_date"),
        Index("ix_backtest_equity_run_date", "run_id", "trading_date"),
    )


__all__ = ["BacktestRun", "BacktestTrade", "BacktestEquity"]

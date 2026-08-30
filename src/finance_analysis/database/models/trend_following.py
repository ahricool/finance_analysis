"""Persistent snapshots for the independent Trend Following strategy."""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base

JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class TrendFollowingSnapshot(Base):
    __tablename__ = "trend_following_snapshot"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    code = Column(String(32), nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="CASCADE"), nullable=False)
    universe_key = Column(String(64), nullable=False)
    market_regime = Column(String(16), nullable=False)
    market_score = Column(Float, nullable=False)
    rank = Column(Integer, nullable=False)
    trend_score = Column(Float, nullable=False)
    rs_score = Column(Float, nullable=False)
    breakout_score = Column(Float, nullable=False)
    alpha_score = Column(Float, nullable=False)
    features = Column(JSON_TYPE, nullable=False, default=dict)
    score_breakdown = Column(JSON_TYPE, nullable=False, default=dict)
    setup = Column(String(32), nullable=False)
    state = Column(String(16), nullable=False)
    action = Column(String(16), nullable=False)
    reference_price = Column(Float, nullable=False)
    atr = Column(Float, nullable=False)
    entry_price = Column(Float)
    signal_date = Column(Date)
    signal_price = Column(Float)
    pending_action = Column(String(24))
    pending_since = Column(Date)
    pending_regime = Column(String(16))
    pending_max_exposure = Column(Float)
    last_add_price = Column(Float)
    highest_close = Column(Float)
    initial_stop = Column(Float)
    trailing_stop = Column(Float)
    next_add_price = Column(Float)
    exit_level = Column(Float)
    units = Column(Integer, nullable=False, default=0)
    opened_at = Column(Date)
    suggested_initial_weight = Column(Float)
    suggested_max_weight = Column(Float)
    reasons = Column(JSON_TYPE, nullable=False, default=list)
    intraday_confirmation = Column(String(16), nullable=False, default="UNAVAILABLE")
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    symbol = relationship("MarketDataSymbol", lazy="joined")

    __table_args__ = (
        UniqueConstraint("market", "trade_date", "code", name="uix_trend_following_market_date_code"),
        CheckConstraint("market IN ('CN', 'US')", name="ck_trend_following_market"),
        CheckConstraint("market_regime IN ('RISK_ON', 'NEUTRAL', 'RISK_OFF')", name="ck_trend_following_regime"),
        CheckConstraint("market_score BETWEEN 0 AND 100", name="ck_trend_following_market_score"),
        CheckConstraint("trend_score BETWEEN 0 AND 100", name="ck_trend_following_trend_score"),
        CheckConstraint("rs_score BETWEEN 0 AND 100", name="ck_trend_following_rs_score"),
        CheckConstraint("breakout_score BETWEEN 0 AND 100", name="ck_trend_following_breakout_score"),
        CheckConstraint("alpha_score BETWEEN 0 AND 100", name="ck_trend_following_alpha_score"),
        CheckConstraint("units BETWEEN 0 AND 4", name="ck_trend_following_units"),
        Index("ix_trend_following_market_date_alpha", "market", "trade_date", "alpha_score"),
        Index("ix_trend_following_symbol_date", "symbol_id", "trade_date"),
        Index("ix_trend_following_market_date_state", "market", "trade_date", "state"),
    )


class TrendFollowingSummary(Base):
    __tablename__ = "trend_following_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    universe_key = Column(String(64), nullable=False)
    benchmark_code = Column(String(32), nullable=False)
    market_regime = Column(String(16), nullable=False)
    market_score = Column(Float, nullable=False)
    suggested_max_exposure = Column(Float, nullable=False)
    universe_size = Column(Integer, nullable=False)
    data_ready_count = Column(Integer, nullable=False)
    data_coverage = Column(Float, nullable=False)
    rankable_count = Column(Integer, nullable=False)
    candidate_count = Column(Integer, nullable=False)
    entry_count = Column(Integer, nullable=False)
    add_count = Column(Integer, nullable=False)
    hold_count = Column(Integer, nullable=False)
    reduce_count = Column(Integer, nullable=False)
    exit_count = Column(Integer, nullable=False)
    warnings = Column(JSON_TYPE, nullable=False, default=list)
    features = Column(JSON_TYPE, nullable=False, default=dict)
    score_breakdown = Column(JSON_TYPE, nullable=False, default=dict)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("market", "trade_date", name="uix_trend_following_summary_market_date"),
        CheckConstraint("market IN ('CN', 'US')", name="ck_trend_following_summary_market"),
        CheckConstraint("market_regime IN ('RISK_ON', 'NEUTRAL', 'RISK_OFF')", name="ck_trend_summary_regime"),
        Index("ix_trend_following_summary_market_date", "market", "trade_date"),
    )


__all__ = ["TrendFollowingSnapshot", "TrendFollowingSummary"]

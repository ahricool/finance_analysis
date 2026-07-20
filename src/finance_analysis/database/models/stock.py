# -*- coding: utf-8 -*-
"""Canonical market-data symbols and raw OHLCV ORM models."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import relationship

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base

SUPPORTED_MARKETS = ("US", "HK", "CN")


def validate_market_data_code(market: str, code: str) -> str:
    """Validate and return the canonical ``ticker.region`` security code."""
    normalized_market = str(market or "").strip().upper()
    normalized_code = str(code or "").strip().upper()
    if normalized_market not in SUPPORTED_MARKETS:
        raise ValueError(f"Unsupported market {market!r}; expected US, HK, or CN")
    suffixes = {"US": (".US",), "HK": (".HK",), "CN": (".SH", ".SZ")}[normalized_market]
    if not normalized_code.endswith(suffixes) or normalized_code.startswith("."):
        expected = "/".join(suffixes)
        raise ValueError(f"Invalid canonical code {code!r} for market={normalized_market}; expected suffix {expected}")
    base = normalized_code.rsplit(".", 1)[0]
    if normalized_market == "HK" and (not base.isdigit() or base.startswith("0")):
        raise ValueError(f"Invalid canonical HK code {code!r}; use an unpadded code such as 700.HK")
    if normalized_market == "CN" and (not base.isdigit() or len(base) != 6):
        raise ValueError(f"Invalid canonical CN code {code!r}; expected six digits plus .SH/.SZ")
    return normalized_code


class MarketDataSymbol(Base):
    """Runtime configuration and canonical identity for one security."""

    __tablename__ = "market_data_symbol"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    code = Column(String(32), nullable=False)
    name = Column(String(255), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    sync_daily = Column(Boolean, nullable=False, default=True)
    sync_minute = Column(Boolean, nullable=False, default=True)
    lot_size = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    daily_bars = relationship("StockDaily", back_populates="symbol", cascade="all, delete-orphan")
    minute_bars = relationship("StockMinute", back_populates="symbol", cascade="all, delete-orphan")
    corporate_actions = relationship(
        "StockCorporateAction", back_populates="symbol", cascade="all, delete-orphan"
    )
    adjustment_factors = relationship(
        "StockAdjustmentFactor", back_populates="symbol", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("code", name="uix_market_data_symbol_code"),
        UniqueConstraint("market", "code", name="uix_market_data_symbol_market_code"),
        CheckConstraint("market IN ('US', 'HK', 'CN')", name="ck_market_data_symbol_market"),
        CheckConstraint("lot_size IS NULL OR lot_size > 0", name="ck_market_data_symbol_lot_size"),
        CheckConstraint(
            "(market = 'US' AND code LIKE '%.US') OR "
            "(market = 'HK' AND code ~ '^[1-9][0-9]*\\.HK$') OR "
            "(market = 'CN' AND code ~ '^[0-9]{6}\\.(SH|SZ)$')",
            name="ck_market_data_symbol_code_suffix",
        ),
        Index("ix_market_data_symbol_sync", "market", "enabled", "sync_daily", "sync_minute"),
    )

    def __repr__(self) -> str:
        return f"<MarketDataSymbol(market={self.market}, code={self.code})>"


@event.listens_for(MarketDataSymbol, "before_insert")
@event.listens_for(MarketDataSymbol, "before_update")
def _validate_symbol(_mapper: Any, _connection: Any, target: MarketDataSymbol) -> None:
    target.market = str(target.market or "").strip().upper()
    target.code = validate_market_data_code(target.market, target.code)


class StockDaily(Base):
    """Unadjusted raw daily OHLCV plus explicitly sourced VWAP metadata."""

    __tablename__ = "stock_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    amount = Column(Float, nullable=True)
    vwap = Column(Float, nullable=True)
    vwap_source = Column(String(32), nullable=True)
    vwap_quality = Column(String(16), nullable=True)
    limit_up = Column(Float, nullable=True)
    limit_down = Column(Float, nullable=True)
    suspended = Column(Boolean, nullable=False, default=False)
    data_source = Column(String(50), nullable=False)
    source_priority = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    symbol = relationship("MarketDataSymbol", back_populates="daily_bars", lazy="joined")

    __table_args__ = (
        UniqueConstraint("symbol_id", "date", name="uix_stock_daily_symbol_date"),
        CheckConstraint("volume >= 0", name="ck_stock_daily_volume_nonnegative"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="ck_stock_daily_amount_nonnegative"),
        CheckConstraint("vwap IS NULL OR vwap > 0", name="ck_stock_daily_vwap_positive"),
        CheckConstraint(
            "vwap_quality IS NULL OR vwap_quality IN ('provider', 'calculated', 'estimated', 'missing')",
            name="ck_stock_daily_vwap_quality",
        ),
        Index("ix_stock_daily_symbol_date", "symbol_id", "date"),
    )

    @property
    def code(self) -> str:
        return self.symbol.code

    @property
    def market(self) -> str:
        return self.symbol.market

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "market": self.market,
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "vwap": self.vwap,
            "vwap_source": self.vwap_source,
            "vwap_quality": self.vwap_quality,
            "limit_up": self.limit_up,
            "limit_down": self.limit_down,
            "suspended": self.suspended,
            "data_source": self.data_source,
            "source_priority": self.source_priority,
        }


class StockMinute(Base):
    """Unadjusted raw one-minute OHLCV; ``bar_time`` is the UTC bar start."""

    __tablename__ = "stock_minute"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="CASCADE"), nullable=False)
    bar_time = Column(DateTime(timezone=True), nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    amount = Column(Float, nullable=True)
    session_type = Column(String(16), nullable=False, default="regular")
    data_source = Column(String(50), nullable=False)
    source_priority = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    symbol = relationship("MarketDataSymbol", back_populates="minute_bars", lazy="joined")

    __table_args__ = (
        UniqueConstraint("symbol_id", "bar_time", name="uix_stock_minute_symbol_time"),
        CheckConstraint("volume >= 0", name="ck_stock_minute_volume_nonnegative"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="ck_stock_minute_amount_nonnegative"),
        CheckConstraint("session_type = 'regular'", name="ck_stock_minute_regular_session"),
        Index("ix_stock_minute_symbol_time", "symbol_id", "bar_time"),
    )

    @property
    def code(self) -> str:
        return self.symbol.code

    @property
    def market(self) -> str:
        return self.symbol.market

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "market": self.market,
            "bar_time": self.bar_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "session_type": self.session_type,
            "data_source": self.data_source,
            "source_priority": self.source_priority,
        }


class StockCorporateAction(Base):
    """A dividend, split, bonus issue, or rights issue reported by a provider."""

    __tablename__ = "stock_corporate_action"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="CASCADE"), nullable=False)
    action_date = Column(Date, nullable=False)
    action_type = Column(String(32), nullable=False)
    cash_dividend = Column(Float, nullable=True)
    split_ratio = Column(Float, nullable=True)
    bonus_ratio = Column(Float, nullable=True)
    rights_ratio = Column(Float, nullable=True)
    rights_price = Column(Float, nullable=True)
    currency = Column(String(8), nullable=True)
    raw_payload = Column(JSON, nullable=False, default=dict)
    data_source = Column(String(50), nullable=False)
    source_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    symbol = relationship("MarketDataSymbol", back_populates="corporate_actions", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "symbol_id", "action_date", "action_type", name="uix_stock_corporate_action_symbol_date_type"
        ),
        CheckConstraint(
            "action_type IN ('dividend', 'split', 'bonus', 'rights')",
            name="ck_stock_corporate_action_type",
        ),
        Index("ix_stock_corporate_action_symbol_date", "symbol_id", "action_date"),
    )


class StockAdjustmentFactor(Base):
    """Per-session factors where qfq price equals raw price times qfq_factor."""

    __tablename__ = "stock_adjustment_factor"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="CASCADE"), nullable=False)
    trade_date = Column(Date, nullable=False)
    qfq_factor = Column(Float, nullable=True)
    hfq_factor = Column(Float, nullable=True)
    hfq_cash = Column(Float, nullable=True)
    adj_close = Column(Float, nullable=True)
    data_source = Column(String(50), nullable=False)
    source_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    symbol = relationship("MarketDataSymbol", back_populates="adjustment_factors", lazy="joined")

    __table_args__ = (
        UniqueConstraint("symbol_id", "trade_date", name="uix_stock_adjustment_factor_symbol_date"),
        CheckConstraint("qfq_factor IS NULL OR qfq_factor > 0", name="ck_stock_adjustment_qfq_positive"),
        CheckConstraint("hfq_factor IS NULL OR hfq_factor > 0", name="ck_stock_adjustment_hfq_positive"),
        Index("ix_stock_adjustment_factor_symbol_date", "symbol_id", "trade_date"),
    )


__all__ = [
    "MarketDataSymbol",
    "StockAdjustmentFactor",
    "StockCorporateAction",
    "StockDaily",
    "StockMinute",
    "SUPPORTED_MARKETS",
    "validate_market_data_code",
]

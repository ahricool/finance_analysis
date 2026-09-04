# -*- coding: utf-8 -*-
"""Security master and persisted daily OHLCV ORM models."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy import JSON, String, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base

SUPPORTED_MARKETS = ("US", "HK", "CN")


def validate_instrument_code(market: str, code: str) -> str:
    """Validate and return a canonical ``ticker.region`` security code."""
    normalized_market = str(market or "").strip().upper()
    normalized_code = str(code or "").strip().upper()
    if normalized_market not in SUPPORTED_MARKETS:
        raise ValueError(f"Unsupported market {market!r}; expected US, HK, or CN")
    suffixes = {"US": (".US",), "HK": (".HK",), "CN": (".SH", ".SZ", ".BJ")}[normalized_market]
    if not normalized_code.endswith(suffixes) or normalized_code.startswith("."):
        expected = "/".join(suffixes)
        raise ValueError(f"Invalid canonical code {code!r} for market={normalized_market}; expected suffix {expected}")
    native_code = normalized_code.rsplit(".", 1)[0]
    if normalized_market == "HK" and (not native_code.isdigit() or native_code.startswith("0")):
        raise ValueError(f"Invalid canonical HK code {code!r}; use an unpadded code such as 700.HK")
    if normalized_market == "CN" and (not native_code.isdigit() or len(native_code) != 6):
        raise ValueError(f"Invalid canonical CN code {code!r}; expected six digits plus .SH/.SZ/.BJ")
    return normalized_code


class Instrument(Base):
    """Canonical security master shared by market data and strategies."""

    __tablename__ = "instrument"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    code = Column(String(32), nullable=False)
    native_code = Column(String(32), nullable=False)
    name = Column(String(255), nullable=False)
    instrument_type = Column(String(16), nullable=False)
    currency = Column(String(8), nullable=False)
    listing_date = Column(Date)
    listing_status = Column(String(16), nullable=False, default="ACTIVE")
    source = Column(String(32), nullable=False)
    instrument_metadata = Column("metadata", JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    daily_bars = relationship("StockDaily", back_populates="instrument", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("code", name="uix_instrument_code"),
        CheckConstraint("market IN ('US', 'HK', 'CN')", name="ck_instrument_market"),
        CheckConstraint("instrument_type IN ('STOCK', 'ETF', 'INDEX')", name="ck_instrument_type"),
        CheckConstraint("currency IN ('CNY', 'USD', 'HKD')", name="ck_instrument_currency"),
        CheckConstraint("listing_status IN ('ACTIVE', 'DELISTED')", name="ck_instrument_listing_status"),
        CheckConstraint(
            "(market = 'US' AND code LIKE '%.US') OR "
            "(market = 'HK' AND code ~ '^[1-9][0-9]*\\.HK$') OR "
            "(market = 'CN' AND code ~ '^[0-9]{6}\\.(SH|SZ|BJ)$')",
            name="ck_instrument_code_suffix",
        ).ddl_if(dialect="postgresql"),
        Index("ix_instrument_market_type_status", "market", "instrument_type", "listing_status"),
    )

    def __repr__(self) -> str:
        return f"<Instrument(market={self.market}, code={self.code})>"


@event.listens_for(Instrument, "before_insert")
@event.listens_for(Instrument, "before_update")
def _validate_instrument(_mapper: Any, _connection: Any, target: Instrument) -> None:
    target.market = str(target.market or "").strip().upper()
    target.code = validate_instrument_code(target.market, target.code)
    target.native_code = str(target.native_code or target.code.rsplit(".", 1)[0])
    target.instrument_type = str(target.instrument_type or "STOCK").upper()
    target.currency = str(target.currency or {"CN": "CNY", "US": "USD", "HK": "HKD"}[target.market]).upper()
    target.listing_status = str(target.listing_status or "ACTIVE").upper()
    target.source = str(target.source or "MANUAL").upper()


class StockDaily(Base):
    """Provider-sourced forward-adjusted daily OHLCV and optional amount."""

    __tablename__ = "stock_daily"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id = Column(Integer, ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    amount = Column(Float)
    data_source = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    instrument = relationship("Instrument", back_populates="daily_bars", lazy="joined")

    __table_args__ = (
        UniqueConstraint("instrument_id", "date", name="uix_stock_daily_instrument_date"),
        CheckConstraint("volume >= 0", name="ck_stock_daily_volume_nonnegative"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="ck_stock_daily_amount_nonnegative"),
        Index("ix_stock_daily_instrument_date", "instrument_id", "date"),
    )

    @property
    def code(self) -> str:
        return self.instrument.code

    @property
    def market(self) -> str:
        return self.instrument.market

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
            "data_source": self.data_source,
        }


__all__ = ["Instrument", "StockDaily", "SUPPORTED_MARKETS", "validate_instrument_code"]

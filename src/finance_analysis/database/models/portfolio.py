# -*- coding: utf-8 -*-
"""Fixed portfolio accounts, instruments, option contracts, and positions."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


DECIMAL_PRECISION = 24
DECIMAL_SCALE = 8


class PortfolioAccount(Base):
    """One of the three immutable market accounts owned by a user."""

    __tablename__ = "portfolio_account"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_code = Column(String(8), nullable=False)
    name = Column(String(64), nullable=False)
    market = Column(String(8), nullable=False)
    currency = Column(String(3), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    cash_balance = relationship(
        "AccountCashBalance", back_populates="account", uselist=False, cascade="all, delete-orphan"
    )
    positions = relationship("Position", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("uid", "account_code", name="uix_portfolio_account_uid_code"),
        UniqueConstraint("uid", "market", name="uix_portfolio_account_uid_market"),
        CheckConstraint("account_code IN ('CN', 'HK', 'US')", name="ck_portfolio_account_code"),
        CheckConstraint("market IN ('CN', 'HK', 'US')", name="ck_portfolio_account_market"),
        CheckConstraint("currency IN ('CNY', 'HKD', 'USD')", name="ck_portfolio_account_currency"),
        CheckConstraint(
            "(account_code = 'CN' AND name = 'A股账户' AND market = 'CN' AND currency = 'CNY') OR "
            "(account_code = 'HK' AND name = '港股账户' AND market = 'HK' AND currency = 'HKD') OR "
            "(account_code = 'US' AND name = '美股账户' AND market = 'US' AND currency = 'USD')",
            name="ck_portfolio_account_identity",
        ),
    )


class AccountCashBalance(Base):
    """The single cash balance associated with a fixed portfolio account."""

    __tablename__ = "account_cash_balance"

    account_id = Column(
        Integer,
        ForeignKey("portfolio_account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    balance = Column(
        Numeric(DECIMAL_PRECISION, DECIMAL_SCALE), nullable=False, default=0, server_default=text("0")
    )
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    account = relationship("PortfolioAccount", back_populates="cash_balance")


class Instrument(Base):
    """Canonical stock, ETF, or manually recorded US option identity."""

    __tablename__ = "instrument"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_type = Column(String(16), nullable=False, index=True)
    market = Column(String(8), nullable=False, index=True)
    canonical_symbol = Column(String(128), nullable=False)
    display_symbol = Column(String(64), nullable=False)
    name = Column(String(255), nullable=True)
    currency = Column(String(3), nullable=False)
    contract_multiplier = Column(
        Numeric(DECIMAL_PRECISION, DECIMAL_SCALE), nullable=False, default=1, server_default=text("1")
    )
    market_data_symbol_id = Column(
        Integer,
        ForeignKey("market_data_symbol.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    extra = Column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    market_data_symbol = relationship("MarketDataSymbol", lazy="joined")
    option_contract = relationship(
        "OptionContract",
        back_populates="instrument",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="OptionContract.instrument_id",
    )
    positions = relationship("Position", back_populates="instrument")

    __table_args__ = (
        UniqueConstraint(
            "market", "asset_type", "canonical_symbol", name="uix_instrument_market_type_symbol"
        ),
        CheckConstraint("asset_type IN ('STOCK', 'ETF', 'OPTION')", name="ck_instrument_asset_type"),
        CheckConstraint("market IN ('CN', 'HK', 'US')", name="ck_instrument_market"),
        CheckConstraint("currency IN ('CNY', 'HKD', 'USD')", name="ck_instrument_currency"),
        CheckConstraint("contract_multiplier > 0", name="ck_instrument_multiplier_positive"),
        CheckConstraint(
            "(market = 'CN' AND currency = 'CNY') OR "
            "(market = 'HK' AND currency = 'HKD') OR "
            "(market = 'US' AND currency = 'USD')",
            name="ck_instrument_market_currency",
        ),
        CheckConstraint(
            "asset_type = 'OPTION' OR contract_multiplier = 1",
            name="ck_instrument_equity_multiplier",
        ),
        CheckConstraint(
            "asset_type != 'OPTION' OR (market = 'US' AND currency = 'USD' AND market_data_symbol_id IS NULL)",
            name="ck_instrument_option_identity",
        ),
    )


class OptionContract(Base):
    """Static contract identity for a manually recorded US option."""

    __tablename__ = "option_contract"

    instrument_id = Column(
        Integer,
        ForeignKey("instrument.id", ondelete="CASCADE"),
        primary_key=True,
    )
    underlying_instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False, index=True)
    expiration_date = Column(Date, nullable=False)
    strike_price = Column(Numeric(DECIMAL_PRECISION, DECIMAL_SCALE), nullable=False)
    option_type = Column(String(4), nullable=False)

    instrument = relationship("Instrument", back_populates="option_contract", foreign_keys=[instrument_id])
    underlying = relationship("Instrument", foreign_keys=[underlying_instrument_id], lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "underlying_instrument_id",
            "expiration_date",
            "strike_price",
            "option_type",
            name="uix_option_contract_identity",
        ),
        CheckConstraint("strike_price > 0", name="ck_option_contract_strike_positive"),
        CheckConstraint("option_type IN ('CALL', 'PUT')", name="ck_option_contract_type"),
    )


class Position(Base):
    """A manually maintained holding in a fixed portfolio account."""

    __tablename__ = "position"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(
        Integer, ForeignKey("portfolio_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False, index=True)
    quantity = Column(Numeric(DECIMAL_PRECISION, DECIMAL_SCALE), nullable=False)
    avg_cost = Column(Numeric(DECIMAL_PRECISION, DECIMAL_SCALE), nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), nullable=False, default="OPEN", server_default=text("'OPEN'"), index=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    account = relationship("PortfolioAccount", back_populates="positions", lazy="joined")
    instrument = relationship("Instrument", back_populates="positions", lazy="joined")

    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uix_position_account_instrument"),
        CheckConstraint("quantity <> 0", name="ck_position_quantity_nonzero"),
        CheckConstraint("avg_cost >= 0", name="ck_position_avg_cost_nonnegative"),
        CheckConstraint("status IN ('OPEN', 'CLOSED', 'EXPIRED')", name="ck_position_status"),
        CheckConstraint(
            "(status = 'OPEN' AND closed_at IS NULL) OR status IN ('CLOSED', 'EXPIRED')",
            name="ck_position_open_closed_at",
        ),
    )

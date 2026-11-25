"""Demo records have no foreign key to the removable shared watchlist."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, String, UniqueConstraint

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class PaperStrategy(Base):
    __tablename__ = "paper_strategy"

    symbol = Column(String(32), primary_key=True)
    config = Column(JSON, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    cursor = Column(BigInteger, nullable=False, default=0)
    status = Column(String(128), nullable=False, default="PAUSED")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class PaperIntent(Base):
    __tablename__ = "paper_intent"
    __table_args__ = (UniqueConstraint("strategy", "bar_time", name="uq_paper_signal_bar"),)

    id = Column(String(36), primary_key=True)
    symbol = Column(String(32), nullable=False)
    strategy = Column(String(32), nullable=True)
    bar_time = Column(BigInteger, nullable=True)
    action = Column(String(24), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False)
    reason = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class PaperExchangeRecord(Base):
    __tablename__ = "paper_exchange_record"

    kind = Column(String(16), primary_key=True)
    symbol = Column(String(32), primary_key=True)
    exchange_id = Column(String(80), primary_key=True)
    timestamp = Column(BigInteger, nullable=False, index=True)
    payload = Column(JSON, nullable=False)


class PaperAccountSnapshot(Base):
    __tablename__ = "paper_account_snapshot"

    id = Column(Integer, primary_key=True)
    observed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    payload = Column(JSON, nullable=False)


class PaperTradeControl(Base):
    __tablename__ = "paper_trade_control"

    id = Column(Integer, primary_key=True)
    account_alias = Column(String(128), nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

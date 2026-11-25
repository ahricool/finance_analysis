"""Live-only account, switch audit and exchange history. Never shares Demo tables."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, String

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class LiveTradeControl(Base):
    __tablename__ = "live_trade_control"

    id = Column(Integer, primary_key=True)
    account_alias = Column(String(128), nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class LiveTradeControlEvent(Base):
    __tablename__ = "live_trade_control_event"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, nullable=False)
    previous = Column(Boolean, nullable=False)
    enabled = Column(Boolean, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class LiveExchangeRecord(Base):
    __tablename__ = "live_exchange_record"

    kind = Column(String(16), primary_key=True)
    symbol = Column(String(32), primary_key=True)
    exchange_id = Column(String(80), primary_key=True)
    timestamp = Column(BigInteger, nullable=False, index=True)
    payload = Column(JSON, nullable=False)


class LiveAccountSnapshot(Base):
    __tablename__ = "live_account_snapshot"

    id = Column(Integer, primary_key=True)
    observed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    payload = Column(JSON, nullable=False)

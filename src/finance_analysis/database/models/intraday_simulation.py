"""Shared research simulation, deliberately independent of portfolio and notifications."""

from sqlalchemy import JSON, Column, Date, DateTime, Index, Integer, String, UniqueConstraint, text
from finance_analysis.database.base import Base


class IntradaySimulationState(Base):
    __tablename__ = "intraday_simulation_state"
    symbol = Column(String(32), primary_key=True)
    payload = Column(JSON, nullable=False)


class IntradaySimulationTrade(Base):
    __tablename__ = "intraday_simulation_trade"
    id = Column(String(256), primary_key=True)
    symbol = Column(String(32), nullable=False, index=True)
    trading_date = Column(Date, nullable=False, index=True)
    process_id = Column(String(192), nullable=False)
    status = Column(String(16), nullable=False)
    payload = Column(JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint("symbol", "process_id"),
        Index("uq_intraday_simulation_open", "symbol", unique=True, postgresql_where=text("status = 'open'")),
    )


class IntradaySimulationEvent(Base):
    __tablename__ = "intraday_simulation_event"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    payload = Column(JSON, nullable=False)

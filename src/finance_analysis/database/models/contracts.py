"""Shared, editable USDT perpetual contract universe and confirmed daily prices."""
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, String

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class FuturesContract(Base):
    __tablename__ = "futures_contract"

    symbol = Column(String(32), primary_key=True)
    category = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class FuturesDailyBar(Base):
    __tablename__ = "futures_daily_bar"

    symbol = Column(String(32), ForeignKey("futures_contract.symbol", ondelete="CASCADE"), primary_key=True)
    timestamp = Column(BigInteger, primary_key=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    turnover = Column(Float, nullable=False)

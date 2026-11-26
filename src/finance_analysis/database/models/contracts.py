"""Shared, editable USDT perpetual contract universe and confirmed daily prices."""
from sqlalchemy import JSON, BigInteger, Column, DateTime, Float, ForeignKey, String

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class FuturesContract(Base):
    __tablename__ = "futures_contract"

    symbol = Column(String(32), primary_key=True)
    category = Column(String(32), nullable=False)
    underlying_symbol = Column(String(64), nullable=True)
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


class FuturesMetricSample(Base):
    """UTC ending boundary. Each source is independently upserted."""
    __tablename__ = "futures_metric_sample"

    symbol = Column(String(32), primary_key=True)
    period = Column(String(4), primary_key=True)
    timestamp = Column(BigInteger, primary_key=True)
    accounts = Column(JSON)
    top_accounts = Column(JSON)
    top_positions = Column(JSON)
    oi = Column(JSON)
    taker = Column(JSON)
    price = Column(JSON)

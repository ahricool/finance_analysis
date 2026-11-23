"""Latest daily forecast for each security in a synchronized market."""

from sqlalchemy import JSON, CheckConstraint, Column, Date, DateTime, Float, Integer, String

from finance_analysis.database.base import Base


class DailyForecastSnapshot(Base):
    __tablename__ = "daily_forecast_snapshot"

    market = Column(String(8), primary_key=True)
    symbol = Column(String(36), primary_key=True)
    anchor_date = Column(Date, nullable=False)
    anchor_close = Column(Float, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)
    model = Column(String(20), nullable=False)
    weights_revision = Column(String(128), nullable=False)
    lookback = Column(Integer, nullable=False)
    bars = Column(JSON, nullable=False)

    __table_args__ = (CheckConstraint("market IN ('CN', 'US')", name="ck_daily_forecast_market"),)

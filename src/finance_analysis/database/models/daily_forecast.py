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


class DailyForecastAccuracyState(Base):
    """Most recent next-session evaluation and cumulative error for its weights."""

    __tablename__ = "daily_forecast_accuracy"

    market = Column(String(8), primary_key=True)
    symbol = Column(String(36), primary_key=True)
    model = Column(String(20), nullable=False)
    weights_revision = Column(String(128), nullable=False)
    target_date = Column(Date, nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    actual_close = Column(Float, nullable=False)
    recent_error = Column(Float, nullable=False)
    recent_baseline_error = Column(Float, nullable=False)
    sample_count = Column(Integer, nullable=False)
    error_sum = Column(Float, nullable=False)
    baseline_error_sum = Column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint("market IN ('CN', 'US')", name="ck_daily_forecast_accuracy_market"),
        CheckConstraint("sample_count > 0", name="ck_daily_forecast_accuracy_count"),
    )

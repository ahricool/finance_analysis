"""Persistent per-symbol opt-ins for the shared minute prediction service."""

from sqlalchemy import Column, String

from finance_analysis.database.base import Base


class MinuteForecastPreference(Base):
    __tablename__ = "minute_forecast_preference"

    symbol = Column(String(32), primary_key=True)

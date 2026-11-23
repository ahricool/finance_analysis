"""Daily Kronos forecasts, separate from observed OHLCV and live minute snapshots."""

from datetime import date, datetime

from pydantic import BaseModel, Field, FiniteFloat

from finance_analysis.minute_forecast.models import HORIZON, Prices


class DailyForecastBar(Prices):
    trade_date: date


class DailyForecast(BaseModel):
    symbol: str
    anchor_date: date
    anchor_close: FiniteFloat = Field(gt=0)
    generated_at: datetime
    model: str
    weights_revision: str
    lookback: int
    bars: list[DailyForecastBar] = Field(min_length=1, max_length=HORIZON)

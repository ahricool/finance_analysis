"""Read-only forward-adjusted daily market data."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class DailyBarItem(BaseModel):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float | None = None


class DailyBarsResponse(BaseModel):
    symbol: str
    market: str
    interval: Literal["1d"] = "1d"
    adjustment: Literal["forward"] = "forward"
    source: str | None = None
    items: list[DailyBarItem]

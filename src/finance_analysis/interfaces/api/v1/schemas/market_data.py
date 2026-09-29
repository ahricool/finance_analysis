"""Read-only forward-adjusted daily market data."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


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
    history_fallback: bool = False
    items: list[DailyBarItem]


class ForwardReturnsRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=5000)
    market: Literal["CN", "US"]
    trade_date: date


class ForwardReturnItem(BaseModel):
    code: str
    forward_return_3d: float | None
    forward_return_5d: float | None
    forward_return_10d: float | None


class ForwardReturnsResponse(BaseModel):
    trade_date: date
    items: list[ForwardReturnItem]

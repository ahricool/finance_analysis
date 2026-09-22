"""Explicit read and asynchronous run contracts."""

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

Market = Literal["CN", "US"]


class Signal(BaseModel):
    source_module: str
    status: Literal["positive", "neutral", "negative", "unavailable"]
    weight: int
    score: float | None
    trade_date: date | None
    source_generated_at: datetime | None
    evidence: dict[str, Any]
    reasons: list[str]


class ConfluenceItem(BaseModel):
    instrument_id: int
    code: str
    name: str
    confluence_score: float | None
    available_weight: int
    available_signal_count: int
    positive_signal_count: int
    eligible: bool
    strong_confluence: bool
    signals: dict[str, Signal]
    reasons: list[str]
    generated_at: datetime


class Ranking(BaseModel):
    market: Market
    trade_date: date | None
    generated_at: datetime | None
    algorithm_version: str | None
    source_availability: dict[str, Any]
    summary: dict[str, int]
    total: int
    items: list[ConfluenceItem]


class Detail(BaseModel):
    market: Market
    trade_date: date
    algorithm_version: str
    item: ConfluenceItem


class RunRequest(BaseModel):
    market: Market = "CN"
    trade_date: date | None = Field(default=None)

    @model_validator(mode="after")
    def no_future(self):
        from finance_analysis.market_review.trading_calendar import get_market_now

        if self.trade_date and self.trade_date > get_market_now(self.market.lower()).date():
            raise ValueError("Cannot generate a future confluence date")
        return self

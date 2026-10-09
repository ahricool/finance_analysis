"""Options research API contracts; raw metric evidence is versioned JSON."""

from pydantic import BaseModel, Field
from datetime import date
from typing import Literal


class OptionsRunRequest(BaseModel):
    symbol: str | None = Field(default=None, max_length=32)
    view: Literal["preview", "official"] | None = None


class OptionsTaskAccepted(BaseModel):
    task_id: str
    status: str = "pending"


class OptionsScanResponse(BaseModel):
    items: list[dict]
    primary_source: str = "yfinance"
    fallback_source: str = "alpaca"
    view: Literal["preview", "official"] = "official"
    trade_date: date | None = None
    available_dates: list[date] = Field(default_factory=list)
    observed_at: str | None = None
    reason: str | None = None
    failed_count: int = 0


class OptionsDetailResponse(BaseModel):
    symbol: str
    latest: dict | None
    daily_history: list[dict]
    events: list[dict]
    analyses: list[dict]
    reason: str | None = None
    view: Literal["preview", "official"] = "official"
    trade_date: date | None = None
    available_dates: list[date] = Field(default_factory=list)

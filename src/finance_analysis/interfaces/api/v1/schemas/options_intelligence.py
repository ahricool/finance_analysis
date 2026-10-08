"""Options research API contracts; raw metric evidence is versioned JSON."""

from pydantic import BaseModel, Field


class OptionsRunRequest(BaseModel):
    symbol: str | None = Field(default=None, max_length=32)


class OptionsTaskAccepted(BaseModel):
    task_id: str
    status: str = "pending"


class OptionsScanResponse(BaseModel):
    items: list[dict]
    primary_source: str = "yfinance"
    fallback_source: str = "alpaca"


class OptionsDetailResponse(BaseModel):
    symbol: str
    latest: dict | None
    daily_history: list[dict]
    events: list[dict]
    analyses: list[dict]
    reason: str | None = None

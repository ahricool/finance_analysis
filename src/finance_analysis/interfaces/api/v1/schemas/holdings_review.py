"""Read-only, private review response contracts."""

from typing import Any, Literal
from pydantic import BaseModel, Field


class ReviewView(BaseModel):
    id: int
    market: Literal["CN", "US"]
    trade_date: str
    status: Literal["processing", "completed", "failed"]
    decision: dict[str, Any] | None
    markdown: str | None
    error: str | None
    started_at: str
    completed_at: str | None
    as_of: str | None
    session_close: str | None
    portfolio: dict[str, Any]
    data_quality: list[str]
    research: dict[str, Any]
    indices: list[dict[str, Any]]
    holdings: list[dict[str, Any]]
    search_evidence: dict[str, Any]
    model: str | None


class ReviewResponse(BaseModel):
    review: ReviewView | None
    requested_date: str
    today: str
    previous_trade_date: str
    scheduled_at: str
    can_run: bool


class ReviewDate(BaseModel):
    trade_date: str
    status: Literal["processing", "completed", "failed"]


class ReviewDates(BaseModel):
    items: list[ReviewDate] = Field(default_factory=list)


class ReviewRun(BaseModel):
    task_id: str

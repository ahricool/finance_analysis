"""Public investment DTOs, independent of storage layout."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Importance = Literal["low", "normal", "high", "critical"]
Actionability = Literal["none", "watch", "consider", "action_required"]
Category = Literal["event", "news", "analysis", "note"]


class TimelineItem(BaseModel):
    id: str
    source_type: Literal["finance_event", "news", "report", "note"]
    source_id: int
    event_time: datetime
    category: Category
    market: str | None = None
    title: str
    summary: str
    symbol: str | None = None
    related_symbols: list[str] = Field(default_factory=list)
    importance: Importance
    actionability: Actionability
    impact: str | None = None
    impact_score: int | None = None
    importance_score: int | None = None
    event_type: str | None = None
    detail_type: str
    detail_payload: dict[str, Any] = Field(default_factory=dict)


class TimelineList(BaseModel):
    items: list[TimelineItem]
    total: int
    next_cursor: str | None
    has_more: bool
    limit: int


class TimelineSummaryItem(BaseModel):
    date: str
    total: int = 0
    critical: int = 0
    high: int = 0
    event_count: int = 0
    news_count: int = 0
    analysis_count: int = 0
    note_count: int = 0

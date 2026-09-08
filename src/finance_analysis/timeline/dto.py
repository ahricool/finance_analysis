"""Public market timeline DTOs, independent of storage layout."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Importance = Literal["low", "normal", "high", "critical"]
Actionability = Literal["none", "watch", "consider", "action_required"]
Category = Literal["event", "news", "analysis"]
CalendarType = Literal["earnings", "macro"]


class TimelineItem(BaseModel):
    id: str
    source_type: Literal["finance_event", "news", "report"]
    source_id: int
    event_time: datetime
    category: Category
    calendar_type: CalendarType | None = None
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

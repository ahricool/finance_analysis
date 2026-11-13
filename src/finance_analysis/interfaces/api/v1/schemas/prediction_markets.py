"""Explicit public catalog and administrator mutation contracts."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class TagView(BaseModel):
    tag_id: str
    slug: str
    label: str
    visible: bool
    rule_group: str
    manual_visible: bool | None
    synced_at: datetime
    event_count: int = 0


class LinkView(BaseModel):
    symbol: str
    name: str
    relation_type: str
    relevance: str
    reason: str
    source: str
    blocked: bool
    judged_at: datetime
    stale: bool


class EventView(BaseModel):
    event_id: str
    title: str
    description: str
    slug: str
    url: str
    tags: list[TagView]
    start_at: datetime | None
    end_at: datetime | None
    closed: bool | None
    archived: bool | None
    retained: bool
    rule_retained: bool
    rule_reason: str
    manual_retained: bool | None
    match_status: str
    synced_at: datetime
    links: list[LinkView]


class EventPage(BaseModel):
    status: str
    items: list[EventView]
    total: int
    page: int
    page_size: int


class TagOverride(BaseModel):
    visible: bool | None


class EventOverride(BaseModel):
    retained: bool | None


class LinkOverride(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    action: Literal["add", "block", "restore"]
    relation_type: Literal["direct", "industry"] = "direct"
    relevance: Literal["high", "medium", "low"] = "high"
    reason: str = Field(default="人工关联", min_length=1, max_length=2000)


class RunRequest(BaseModel):
    job: Literal["catalog", "matching"]
    slug: str | None = Field(default=None, max_length=600)
    event_id: str | None = None


class OutcomeView(BaseModel):
    id: str | None
    label: str
    probability: float | None
    price_type: str
    missing_reason: str | None


class MarketView(BaseModel):
    id: str
    question: str | None = None
    version: str | None = None
    end_at: str | None = None
    closed: bool | None = None
    resolved: bool = False
    observed_at: str | None = None
    outcomes: list[OutcomeView]


class DynamicStatus(BaseModel):
    status: str
    fetched_at: str | None = None
    cache_status: str = "miss"
    stale: bool = False
    error: str | None = None


class LiveResponse(DynamicStatus):
    event_id: str | None = None
    closed: bool | None = None
    archived: bool | None = None
    observed_at: str | None = None
    source: str | None = None
    protocol_coverage: list[str] = Field(default_factory=list)
    markets: list[MarketView] = Field(default_factory=list)


class HistoryPoint(BaseModel):
    timestamp: int
    price: float
    resolution_seconds: int


class HistoryChange(BaseModel):
    percentage_points: float | None
    reason: str | None


class HistoryResponse(DynamicStatus):
    points: list[HistoryPoint] = Field(default_factory=list)
    changes: dict[str, HistoryChange] = Field(default_factory=dict)
    series_as_of: int | None = None
    source: str | None = None
    window: str | None = None
    market_id: str | None = None
    outcome_id: str | None = None
    closed: bool | None = None
    resolved: bool = False

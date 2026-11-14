"""Ephemeral stock search and on-demand Polymarket contracts."""

from pydantic import BaseModel, Field


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


class SearchEvent(BaseModel):
    event_id: str
    title: str
    url: str
    end_at: str | None = None
    closed: bool | None = None
    volume_24h: float | None = None


class SearchResponse(DynamicStatus):
    symbol: str | None = None
    queries: list[str] = Field(default_factory=list)
    items: list[SearchEvent] = Field(default_factory=list)
    partial: bool = False
    sort: str = "official_relevance"

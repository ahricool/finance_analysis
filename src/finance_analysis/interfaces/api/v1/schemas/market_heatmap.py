"""Read-only heatmap API contract."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HeatmapStock(BaseModel):
    code: str
    name: str
    market_cap: float
    price: float | None
    change_pct: float | None
    group_code: str
    group_name: str
    quote_time: datetime | None


class HeatmapSnapshot(BaseModel):
    market: Literal["CN", "US"]
    source: str
    generated_at: datetime
    data_as_of: datetime | None
    data_latest_at: datetime | None
    classification_observed_at: datetime | None
    min_market_cap: float
    refresh_seconds: int
    excluded_count: int
    unclassified_count: int
    items: list[HeatmapStock]


class HeatmapResponse(BaseModel):
    status: Literal["ready", "empty", "stale"]
    snapshot: HeatmapSnapshot | None

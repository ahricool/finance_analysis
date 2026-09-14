"""ETF Rotation API contracts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class ETFRotationRunRequest(BaseModel):
    market: Literal["CN", "US"] = "CN"
    trade_date: date | None = None


class ETFRankSeries(BaseModel):
    code: str
    name: str
    ranks: list[int | None]


class ETFRankHistoryResponse(BaseModel):
    market: Literal["CN", "US"]
    dates: list[date]
    official_count: int
    preview_date: date | None
    preview_time: datetime | None
    generated_at: datetime | None
    series: list[ETFRankSeries]


__all__ = ["ETFRotationRunRequest", "ETFRankSeries", "ETFRankHistoryResponse"]

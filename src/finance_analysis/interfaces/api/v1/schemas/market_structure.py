"""Read and background-run contracts for official market snapshots."""

from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, model_validator


class MarketStructureResponse(BaseModel):
    market: Literal["CN", "US"]
    trade_date: date
    expected_trade_date: date
    breadth: dict[str, float | None]
    rotation: dict[str, float | None]
    leadership: dict[str, float | None]
    metrics: dict[str, Any]


class MarketStructureRunRequest(BaseModel):
    market: Literal["CN", "US"] = "CN"
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("Both start_date and end_date are required")
        if self.start_date and (self.trade_date or self.start_date > self.end_date):
            raise ValueError("Use either trade_date or an ordered date range")
        return self

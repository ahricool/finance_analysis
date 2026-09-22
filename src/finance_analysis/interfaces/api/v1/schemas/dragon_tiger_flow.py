"""Explicit public amounts; normalized raw payloads and credentials are never exposed."""

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

Board = Literal["all", "org", "hot_money"]


class Amounts(BaseModel):
    net_value: float | None
    buy_value: float | None
    sell_value: float | None
    org_net_value: float | None
    hot_money_net_value: float | None


class Summary(Amounts):
    stock_count: int
    top5_concentration: float | None


class Concept(BaseModel):
    id: str
    name: str
    net_value: float | None
    org_net_value: float | None
    hot_money_net_value: float | None
    stock_count: int
    values: list[float | None]


class Evidence(Amounts):
    symbol: str
    name: str
    trade_date: date
    range_days: Literal[1, 3]
    concepts: list[str]
    concept_id: str
    concept_name: str
    allocation_count: int
    original_net_value: float | None
    stock_net_value: float | None


class HotMoneyDetail(BaseModel):
    symbol: str
    name: str
    trade_date: date
    range_days: Literal[1, 3]
    hot_money_name: str
    hot_money_item_net_value: float | None


class Overview(BaseModel):
    version: str
    revision: str
    board: Board
    range_days: Literal[1, 3]
    trade_date: date | None
    expected_trade_date: date | None = None
    dates: list[date]
    complete: bool
    missing_dates: list[date]
    excluded_undisclosed_count: int
    summary: Summary
    concepts: list[Concept]
    evidence: list[Evidence]
    hot_money_details: list[HotMoneyDetail]
    source_quality: list[dict[str, Any]]
    attribution: str
    source: str
    unit: str


class DateStatus(BaseModel):
    trade_date: date
    generated_at: datetime
    boards: list[Board]
    errors: dict[str, str]


class StockContribution(BaseModel):
    symbol: str
    name: str
    net_value: float | None
    rows: list[Evidence]


class ConceptDetail(BaseModel):
    revision: str
    concept: Concept
    stocks: list[StockContribution]


class StockDetail(BaseModel):
    revision: str
    rows: list[Evidence]
    hot_money_details: list[HotMoneyDetail]


class RunRequest(BaseModel):
    trade_date: date | None = None
    backfill_days: int | None = Field(None, ge=1, le=31)
    missing_only: bool = True

    @model_validator(mode="after")
    def exclusive(self):
        if self.trade_date is not None and self.backfill_days is not None:
            raise ValueError("trade_date 与 backfill_days 不能同时提供")
        return self


class RunResponse(BaseModel):
    task_id: str
    status: str = "pending"

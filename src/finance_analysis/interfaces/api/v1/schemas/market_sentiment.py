"""Authenticated observation contracts. Ratios are decimal; money is CNY."""

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

PoolKind = Literal["limit_up", "limit_down", "limit_break"]


class Promotion(BaseModel):
    source_date: date | None
    target_date: date
    complete: bool
    numerator: int | None
    denominator: int | None
    ratio: float | None
    promoted_codes: list[str]
    not_promoted_codes: list[str]


class Observation(BaseModel):
    trade_date: date
    previous_trade_date: date | None
    scope: str
    rule_version: str
    early_time_threshold: str
    state: Literal["UNKNOWN", "ICE", "COOLING", "REPAIR", "DIVERGENCE", "CLIMAX", "ACTIVE", "NEUTRAL"]
    heat_score: float | None
    state_reasons: list[str]
    upstream_total: int
    excluded_st_count: int
    excluded_new_count: int
    excluded_union_count: int
    unknown_scope_count: int
    scope_complete: bool
    boards_complete: bool
    limit_up_count: int | None
    first_board_count: int | None
    multi_board_count: int | None
    highest_board: int | None
    board_distribution: dict[str, int | None]
    unconfirmed_board_count: int
    early_limit_up_count: int | None
    valid_limit_up_time_count: int | None
    time_coverage: float | None
    early_limit_up_ratio: float | None
    seal_retention_median: float | None
    valid_seal_retention_count: int | None
    seal_retention_coverage: float | None
    seal_money_sum: float | None
    valid_seal_money_count: int | None
    seal_money_coverage: float | None
    reasons: list[dict[str, Any]]
    promotions: dict[str, Promotion]
    changes: dict[str, float | None]
    quality: dict[str, Any]
    supplements: dict[str, Any]
    source_timestamp: datetime
    fetched_at: datetime
    generated_at: datetime


class OverviewResponse(BaseModel):
    trade_date: date | None
    expected_trade_date: date
    observation: Observation | None
    industry_top: list[dict[str, Any]]


class HistoryResponse(BaseModel):
    dates: list[date]
    items: list[Observation | None]


class PoolResponse(BaseModel):
    trade_date: date | None
    kind: PoolKind
    available: bool
    total: int | None
    upstream_total: int | None
    page: int
    size: int
    items: list[dict[str, Any]]
    basis: str


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


class LadderSource(BaseModel):
    trade_date: date
    requested_trade_date: date | None
    source_kind: str
    source_timestamp: datetime
    fetched_at: datetime
    total: int
    item_count: int
    quality: dict[str, Any]
    window: dict[str, Any]
    items: list[dict[str, Any]]


class LadderResponse(BaseModel):
    as_of: date | None
    source: LadderSource | None
    basis: str

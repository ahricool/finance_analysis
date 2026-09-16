"""Public, credential-free industry observation contracts (decimal returns)."""

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

IndustryState = Literal["EMERGING", "STRONG", "NEUTRAL", "COOLING", "WEAK"]


class IndustrySnapshot(BaseModel):
    trade_date: date
    industry_code: str
    industry_name: str
    state: IndustryState
    data_timestamp: datetime
    members_observed_at: datetime
    created_at: datetime
    updated_at: datetime
    quality: dict[str, Any]
    close: float | None = None
    ret_1d: float | None = None
    ret_5d: float | None = None
    ret_10d: float | None = None
    ret_20d: float | None = None
    rs_5d: float | None = None
    rs_10d: float | None = None
    rs_20d: float | None = None
    rs_5d_percentile: float | None = None
    rs_10d_percentile: float | None = None
    rs_20d_percentile: float | None = None
    strength_score: float | None = None
    previous_5d_return: float | None = None
    momentum_acceleration_5d: float | None = None
    acceleration_percentile: float | None = None
    turnover_ratio_5d: float | None = None
    up_ratio: float | None = None
    above_ma5_ratio: float | None = None
    above_ma20_ratio: float | None = None
    equal_weight_return: float | None = None
    rs_5d_rank: int | None = None
    rs_10d_rank: int | None = None
    rs_20d_rank: int | None = None
    strength_rank: int | None = None
    rank_change_1d: int | None = None
    rank_change_3d: int | None = None
    rank_change_5d: int | None = None
    constituent_count: int | None = None
    valid_constituent_count: int | None = None
    up_count: int | None = None
    down_count: int | None = None
    flat_count: int | None = None


class RankingResponse(BaseModel):
    trade_date: date | None
    expected_trade_date: date
    source: str = "同花顺金融数据 API / 扶摇"
    items: list[IndustrySnapshot]


class HistoryResponse(BaseModel):
    dates: list[date]
    items: list[IndustrySnapshot]


class DetailResponse(BaseModel):
    current: IndustrySnapshot
    history: list[IndustrySnapshot]


class Constituent(BaseModel):
    code: str
    name: str
    price: float | None
    change_pct: float | None
    volume: float | None
    amount: float | None
    above_ma5: bool | None
    above_ma20: bool | None


class ConstituentsResponse(BaseModel):
    industry_code: str
    trade_date: date
    members_observed_at: datetime
    basis: str
    constituent_count: int
    valid_constituent_count: int
    up_count: int
    down_count: int
    flat_count: int
    up_ratio: float | None
    above_ma5_ratio: float | None
    above_ma20_ratio: float | None
    equal_weight_return: float | None
    items: list[Constituent] = Field(default_factory=list)

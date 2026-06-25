# -*- coding: utf-8 -*-
"""Pydantic schemas for stock_list (持仓股) endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from finance_analysis.stocks.markets import normalize_market_type
from finance_analysis.core.time import utc_isoformat


class StockHoldingCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=16, description="股票代码")
    name: Optional[str] = Field(None, max_length=64, description="股票名称（可选）")
    quantity: Decimal = Field(Decimal("0"), ge=0, description="持仓数量（股），支持碎股")
    avg_cost: Optional[Decimal] = Field(None, ge=0, description="每股平均持仓成本")
    opened_at: Optional[datetime] = Field(None, description="首次建仓时间")
    market_type: str = Field("CN", description="市场类型：CN=A股，US=美股，HK=港股")
    notes: Optional[str] = Field(None, description="备注（可选）")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("market_type")
    @classmethod
    def normalize_market(cls, v: str) -> str:
        return normalize_market_type(v)

    @field_validator("quantity", "avg_cost", mode="before")
    @classmethod
    def reject_float_values(cls, v):
        if isinstance(v, float):
            raise ValueError("decimal values must be provided as strings, not float")
        return v


class StockHoldingUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    quantity: Optional[Decimal] = Field(None, ge=0)
    avg_cost: Optional[Decimal] = Field(None, ge=0)
    opened_at: Optional[datetime] = None
    notes: Optional[str] = None

    @field_validator("quantity", "avg_cost", mode="before")
    @classmethod
    def reject_float_values(cls, v):
        if isinstance(v, float):
            raise ValueError("decimal values must be provided as strings, not float")
        return v


class StockHoldingResponse(BaseModel):
    id: int
    code: str
    name: Optional[str]
    quantity: Decimal
    avg_cost: Optional[Decimal]
    opened_at: Optional[datetime]
    market_type: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return utc_isoformat(value) or ""

    @field_serializer("opened_at")
    def serialize_optional_datetime(self, value: Optional[datetime]) -> Optional[str]:
        return utc_isoformat(value) if value is not None else None

    @field_serializer("quantity", "avg_cost")
    def serialize_decimal(self, value: Optional[Decimal]) -> Optional[str]:
        return format(value, "f") if value is not None else None


class StockListResponse(BaseModel):
    items: List[StockHoldingResponse]
    total: int

# -*- coding: utf-8 -*-
"""Pydantic schemas for stock_list (持仓股) endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from finance_analysis.stocks.markets import normalize_market_type
from finance_analysis.core.time import utc_isoformat


class StockHoldingCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=16, description="股票代码")
    name: Optional[str] = Field(None, max_length=64, description="股票名称（可选）")
    quantity: int = Field(0, ge=0, description="持仓数量（股）")
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


class StockHoldingUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    quantity: Optional[int] = Field(None, ge=0)
    market_type: Optional[str] = Field(None, description="市场类型：CN=A股，US=美股，HK=港股")
    notes: Optional[str] = None


class StockHoldingResponse(BaseModel):
    id: int
    code: str
    name: Optional[str]
    quantity: int
    market_type: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return utc_isoformat(value) or ""


class StockListResponse(BaseModel):
    items: List[StockHoldingResponse]
    total: int

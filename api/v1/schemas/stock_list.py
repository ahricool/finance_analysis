# -*- coding: utf-8 -*-
"""Pydantic schemas for stock_list (持仓股) endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class StockHoldingCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=16, description="股票代码")
    name: Optional[str] = Field(None, max_length=64, description="股票名称（可选）")
    quantity: int = Field(0, ge=0, description="持仓数量（股）")
    notes: Optional[str] = Field(None, description="备注（可选）")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()


class StockHoldingUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    quantity: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None


class StockHoldingResponse(BaseModel):
    id: int
    code: str
    name: Optional[str]
    quantity: int
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StockListResponse(BaseModel):
    items: List[StockHoldingResponse]
    total: int

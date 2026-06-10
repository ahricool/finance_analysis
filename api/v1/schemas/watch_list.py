# -*- coding: utf-8 -*-
"""Pydantic schemas for watch_list (自选股) endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from src.services.market_type_utils import normalize_market_type
from src.time_utils import utc_isoformat


class WatchListItemCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=16, description="股票代码")
    name: Optional[str] = Field(None, max_length=64, description="股票名称（可选）")
    notes: Optional[str] = Field(None, description="备注（可选）")
    market_type: str = Field("CN", description="市场类型：CN=A股，US=美股，HK=港股")
    is_favorite: bool = Field(False, description="是否特别关注")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("market_type")
    @classmethod
    def normalize_market(cls, v: str) -> str:
        return normalize_market_type(v)


class WatchListItemUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    notes: Optional[str] = None
    market_type: Optional[str] = Field(None, description="市场类型：CN=A股，US=美股，HK=港股")
    is_favorite: Optional[bool] = Field(None, description="是否特别关注")


class WatchListItemResponse(BaseModel):
    id: int
    code: str
    name: Optional[str]
    notes: Optional[str]
    market_type: str
    is_favorite: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return utc_isoformat(value) or ""


class WatchListResponse(BaseModel):
    items: List[WatchListItemResponse]
    total: int

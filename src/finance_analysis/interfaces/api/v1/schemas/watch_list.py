# -*- coding: utf-8 -*-
"""Pydantic schemas for watch_list (自选股) endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from finance_analysis.stocks.markets import canonical_watch_list_code, normalize_market_type
from finance_analysis.core.time import utc_isoformat
from finance_analysis.database.repositories.watch_list import normalize_tag_name


class WatchListTagName(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_tag_name(value)[0]


class WatchListTagInput(BaseModel):
    id: Optional[int] = Field(None, gt=0)
    name: Optional[str] = None

    @model_validator(mode="after")
    def validate_reference(self) -> WatchListTagInput:
        if (self.id is None) == (self.name is None):
            raise ValueError("标签须提供 id 或新标签名称，不能同时提供")
        if self.name is not None:
            self.name = normalize_tag_name(self.name)[0]
        return self


class WatchListTagResponse(BaseModel):
    id: int
    name: str
    model_config = {"from_attributes": True}


class WatchListItemCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=16, description="股票代码")
    name: Optional[str] = Field(None, max_length=64, description="股票名称（可选）")
    notes: Optional[str] = Field(None, description="备注（可选）")
    market_type: str = Field("CN", description="市场类型：CN=A股，US=美股，HK=港股")
    is_favorite: bool = Field(False, description="是否特别关注")
    tags: List[WatchListTagInput] = Field(default_factory=list, max_length=50)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("market_type")
    @classmethod
    def normalize_market(cls, v: str) -> str:
        return normalize_market_type(v)

    @model_validator(mode="after")
    def validate_code_market(self) -> WatchListItemCreate:
        canonical_watch_list_code(self.code, self.market_type)
        return self


class WatchListItemUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    notes: Optional[str] = None
    market_type: Optional[str] = Field(None, description="市场类型：CN=A股，US=美股，HK=港股")
    is_favorite: Optional[bool] = Field(None, description="是否特别关注")
    tags: List[WatchListTagInput] = Field(default_factory=list, max_length=50)


class WatchListItemResponse(BaseModel):
    id: int
    code: str
    name: Optional[str]
    notes: Optional[str]
    market_type: str
    is_favorite: bool
    created_at: datetime
    updated_at: datetime
    validation_error: Optional[str] = None
    tags: List[WatchListTagResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return utc_isoformat(value) or ""


class WatchListResponse(BaseModel):
    items: List[WatchListItemResponse]
    total: int

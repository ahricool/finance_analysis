# -*- coding: utf-8 -*-
"""Pydantic schemas for watch_list (自选股) endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class WatchListItemCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=16, description="股票代码")
    name: Optional[str] = Field(None, max_length=64, description="股票名称（可选）")
    notes: Optional[str] = Field(None, description="备注（可选）")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()


class WatchListItemUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    notes: Optional[str] = None


class WatchListItemResponse(BaseModel):
    id: int
    code: str
    name: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WatchListResponse(BaseModel):
    items: List[WatchListItemResponse]
    total: int

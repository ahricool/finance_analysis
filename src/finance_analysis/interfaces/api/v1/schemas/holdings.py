# -*- coding: utf-8 -*-
"""API schemas for DB portfolio and BST markers."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TradeRequest(BaseModel):
    symbol: Optional[str] = None
    account_id: Optional[int] = None
    position_id: Optional[int] = None
    quantity: str
    price: str
    executed_at: Optional[datetime] = None
    note: Optional[str] = None
    asset_type: Optional[str] = "STOCK"


class CashRequest(BaseModel):
    account_id: int
    amount: str


class PositionUpdateRequest(BaseModel):
    trade_engine_enabled: Optional[bool] = None

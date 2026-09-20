# -*- coding: utf-8 -*-
"""API schemas for DB portfolio, Google Sheet secondary source, and BST markers."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_serializer

from finance_analysis.core.time import utc_isoformat  # pragma: allowlist secret


class HoldingsConnectRequest(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1, description="Google Sheet ID 或 docs.google.com URL")
    return_path: Optional[str] = Field("/market/holdings", description="授权完成后的站内路径")


class HoldingsConnectResponse(BaseModel):
    authorization_url: str
    return_path: str
    auth_status: str


class HoldingsDisconnectResponse(BaseModel):
    auth_status: str
    google_revoke: str


class HoldingsSourceResponse(BaseModel):
    google_configured: bool
    holdings_enabled: bool
    missing_config: list[str] = Field(default_factory=list)
    source_id: Optional[int] = None
    spreadsheet_id: Optional[str] = None
    schema_version: Optional[str] = None
    auth_status: str
    sync_status: Optional[str] = None
    enabled: bool
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    published_generation: int = 0
    content_hash: Optional[str] = None
    config_version: int = 1
    policy_version: int = 1
    can_background_sync: bool = False

    @field_serializer("last_attempt_at", "last_success_at")
    def _dt(self, value: datetime | None) -> str | None:
        return utc_isoformat(value)


class HoldingsSyncResponse(BaseModel):
    task_id: Optional[str] = None
    changed: Optional[bool] = None
    generation: Optional[int] = None
    status: str


class HoldingsPolicyUpdate(BaseModel):
    max_symbol_weight: Optional[float] = None
    risk_per_symbol: Optional[float] = None
    total_open_risk: Optional[float] = None
    max_gross_exposure: Optional[float] = None
    vwap_mode: Optional[str] = None


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
    executed_at: Optional[datetime] = None
    note: Optional[str] = None


class PositionUpdateRequest(BaseModel):
    trade_engine_enabled: Optional[bool] = None
    strategy_key: Optional[str] = None

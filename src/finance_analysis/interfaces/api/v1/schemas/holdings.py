# -*- coding: utf-8 -*-
"""API schemas for Google Sheet holdings. Money fields are decimal strings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

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


class HoldingsRebaseRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    account_id: str
    position_id: str
    leg_id: str
    expected_source_version: int
    expected_state_version: int
    observed_from: Optional[datetime] = None
    high_watermark: Optional[str] = None
    profit_stage: Optional[str] = None
    active_stop: Optional[str] = None


class HoldingsPlanCancelRequest(BaseModel):
    account_id: str
    position_id: str
    expected_state_version: int
    reason: str = Field(..., min_length=1)

# -*- coding: utf-8 -*-
"""Versioned holdings snapshot models. JSON money fields are decimal strings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from finance_analysis.core.time import coerce_aware_utc  # pragma: allowlist secret

SCHEMA_VERSION = "holdings.snapshot.v1"
LegRole = Literal["CORE", "ADDON"]
LegStatus = Literal["OPEN", "CLOSED"]
CoverageStatus = Literal["COVERED", "UNCOVERED_MARKET", "UNCOVERED_ASSET", "UNCOVERED_SIDE"]
AccountValidity = Literal["VALID", "EMPTY_VALID", "NAV_STALE", "NAV_MISSING", "INCOMPLETE"]
SnapshotStatus = Literal["VALID", "REJECTED", "UNAVAILABLE"]


def _decimal_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


class HoldingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_serializer("*")
    def _serialize(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, datetime):
            aware = coerce_aware_utc(value)
            return aware.isoformat() if aware else None
        return value


class ParsedAccount(HoldingsModel):
    account_id: str
    account_name: str
    base_currency: str
    net_asset: Decimal | None = None
    nav_as_of: datetime | None = None
    holdings_as_of: datetime | None = None
    positions_complete: bool
    cash: Decimal | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
    validity: AccountValidity = "VALID"
    validity_reason: str | None = None


class ParsedLeg(HoldingsModel):
    account_id: str
    position_id: str
    leg_id: str
    leg_role: LegRole
    symbol: str
    canonical_symbol: str | None = None
    asset_type: str
    quantity: Decimal
    entry_price: Decimal
    entry_time: datetime
    status: LegStatus
    currency: str | None = None
    initial_stop: Decimal | None = None
    available_quantity: Decimal | None = None
    available_as_of: datetime | None = None
    risk_group: str | None = None
    manual_market_value: Decimal | None = None
    valuation_as_of: datetime | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
    coverage: CoverageStatus = "COVERED"
    coverage_reason: str | None = None

    @field_validator("leg_role")
    @classmethod
    def _role(cls, value: str) -> str:
        return str(value).strip().upper()

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        return str(value).strip().upper()


class ParsedPosition(HoldingsModel):
    account_id: str
    position_id: str
    symbol: str
    canonical_symbol: str | None = None
    asset_type: str
    currency: str | None = None
    legs: list[ParsedLeg]


class HoldingsSnapshot(HoldingsModel):
    schema_version: str = SCHEMA_VERSION
    uid: int
    source_id: int
    spreadsheet_id: str
    generation: int
    content_hash: str
    fetched_at: datetime
    timezone: str
    status: SnapshotStatus = "VALID"
    rejection_code: str | None = None
    rejection_message: str | None = None
    accounts: list[ParsedAccount] = Field(default_factory=list)
    positions: list[ParsedPosition] = Field(default_factory=list)
    uncovered_legs: list[ParsedLeg] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def open_legs(self) -> list[ParsedLeg]:
        return [leg for position in self.positions for leg in position.legs if leg.status == "OPEN"]

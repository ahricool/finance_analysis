"""Strict request and response schemas for portfolio APIs."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from finance_analysis.core.time import utc_isoformat


def _require_decimal_string(value, field_name: str):
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be provided as a JSON string")
    return value


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CashBalanceUpdate(StrictRequest):
    balance: Decimal

    @field_validator("balance", mode="before")
    @classmethod
    def validate_balance_string(cls, value):
        return _require_decimal_string(value, "balance")


class EquityPositionCreate(StrictRequest):
    canonical_symbol: str = Field(min_length=1, max_length=128)
    display_symbol: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    asset_type: Literal["STOCK", "ETF"]
    quantity: Decimal
    avg_cost: Decimal
    opened_at: datetime | None = None
    notes: str | None = None

    @field_validator("quantity", "avg_cost", mode="before")
    @classmethod
    def validate_decimal_strings(cls, value, info):
        return _require_decimal_string(value, info.field_name)


class OptionPositionCreate(StrictRequest):
    underlying_canonical_symbol: str = Field(min_length=1, max_length=128)
    underlying_display_symbol: str = Field(min_length=1, max_length=64)
    underlying_name: str | None = Field(default=None, max_length=255)
    underlying_asset_type: Literal["STOCK", "ETF"]
    option_type: Literal["CALL", "PUT"]
    expiration_date: date
    strike_price: Decimal
    quantity: Decimal
    avg_cost: Decimal
    contract_multiplier: Decimal = Field(default="100")
    opened_at: datetime | None = None
    notes: str | None = None

    @field_validator("strike_price", "quantity", "avg_cost", "contract_multiplier", mode="before")
    @classmethod
    def validate_decimal_strings(cls, value, info):
        return _require_decimal_string(value, info.field_name)


class PositionUpdate(StrictRequest):
    quantity: Decimal | None = None
    avg_cost: Decimal | None = None
    opened_at: datetime | None = None
    status: Literal["OPEN", "CLOSED", "EXPIRED"] | None = None
    closed_at: datetime | None = None
    notes: str | None = None

    @field_validator("quantity", "avg_cost", mode="before")
    @classmethod
    def validate_optional_decimal_strings(cls, value, info):
        if value is None:
            return None
        return _require_decimal_string(value, info.field_name)


class PortfolioAccountResponse(BaseModel):
    id: int
    account_code: Literal["CN", "HK", "US"]
    name: str
    market: Literal["CN", "HK", "US"]
    currency: Literal["CNY", "HKD", "USD"]
    cash_balance: str


class OptionContractResponse(BaseModel):
    underlying_canonical_symbol: str
    underlying_display_symbol: str
    underlying_name: str | None
    option_type: Literal["CALL", "PUT"]
    expiration_date: date
    strike_price: str
    days_to_expiration: int
    expiration_action_required: bool


class PositionResponse(BaseModel):
    id: int
    account_id: int
    account_code: Literal["CN", "HK", "US"]
    asset_type: Literal["STOCK", "ETF", "OPTION"]
    market: Literal["CN", "HK", "US"]
    currency: Literal["CNY", "HKD", "USD"]
    canonical_symbol: str
    display_symbol: str
    name: str | None
    quantity: str
    position_side: Literal["LONG", "SHORT"]
    avg_cost: str
    contract_multiplier: str
    cost_amount: str
    opened_at: datetime | None
    status: Literal["OPEN", "CLOSED", "EXPIRED"]
    closed_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    option: OptionContractResponse | None

    @field_serializer("opened_at", "closed_at")
    def serialize_optional_datetime(self, value: datetime | None) -> str | None:
        return utc_isoformat(value) if value is not None else None

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return utc_isoformat(value) or ""

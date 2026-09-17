# -*- coding: utf-8 -*-
"""Versioned JSONB models for position/leg risk state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from finance_analysis.core.time import coerce_aware_utc  # pragma: allowlist secret

LEGS_STATE_VERSION = "legs_state.v1"
PLAN_VERSION = "active_plan.v1"
ProfitStage = Literal["UNKNOWN", "A", "B", "C"]
PlanStatus = Literal["NONE", "PENDING", "SATISFIED_BY_SHEET", "CANCELED", "SUPERSEDED"]
Action = Literal["HOLD", "WATCH", "REDUCE", "EXIT"]
Execution = Literal["UNKNOWN", "AVAILABLE", "PARTIALLY_AVAILABLE", "BLOCKED"]


class RiskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_serializer("*")
    def _ser(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, datetime):
            aware = coerce_aware_utc(value)
            return aware.isoformat() if aware else None
        return value


class LegRiskState(RiskModel):
    schema_version: str = LEGS_STATE_VERSION
    leg_id: str
    role: Literal["CORE", "ADDON"]
    entry_price: Decimal
    entry_time: datetime
    input_fingerprint: str
    last_quantity: Decimal
    high_watermark: Decimal | None = None
    profit_stage: ProfitStage = "UNKNOWN"
    active_stop: Decimal | None = None
    structure_stop: Decimal | None = None
    observed_from: datetime | None = None
    coverage: str = "PARTIAL"
    fixed_target: Decimal | None = None
    calibration_required: bool = False


class LegsStateDocument(RiskModel):
    schema_version: str = LEGS_STATE_VERSION
    last_vwap_mode: str | None = None
    legs: dict[str, LegRiskState] = Field(default_factory=dict)


class ActivePlan(RiskModel):
    schema_version: str = PLAN_VERSION
    revision: int = 0
    status: PlanStatus = "NONE"
    action: Action = "HOLD"
    episode_id: str | None = None
    bound_leg_ids: list[str] = Field(default_factory=list)
    leg_targets: dict[str, str] = Field(default_factory=dict)
    position_target: str | None = None
    reason: str | None = None
    created_bar_end: datetime | None = None
    execution: Execution = "UNKNOWN"


def fingerprint(leg_id: str, symbol: str, role: str, entry_price: Decimal, entry_time: datetime) -> str:
    aware = coerce_aware_utc(entry_time)
    return "|".join(
        [leg_id, symbol, role, format(entry_price, "f"), aware.isoformat() if aware else ""]
    )

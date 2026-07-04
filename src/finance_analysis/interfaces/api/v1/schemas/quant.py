"""Quant API write contracts."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class DatasetBuildRequest(BaseModel):
    market: str = "US"
    universe: str = "us_ai_semiconductor"
    date_from: date
    date_to: date


class EventCreateRequest(BaseModel):
    code: str | None = None
    market: str
    event_type: str
    published_at: str
    available_at: str | None = None
    effective_at: str | None = None
    direction: str = "neutral"
    importance: float = Field(.5, ge=0, le=1)
    confidence: float = Field(1, ge=0, le=1)
    surprise_value: float | None = None
    source: str = "manual"
    source_event_id: str | None = None
    title: str
    summary: str | None = None
    raw_content: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class EventImportRequest(BaseModel):
    format: str = "json"
    items: list[dict[str, Any]] = Field(default_factory=list)
    csv_content: str | None = None


class ModelRunCreateRequest(BaseModel):
    model_key: str = "cross_section_lgbm"
    model_version: str
    market: str = "US"
    universe: str = "us_ai_semiconductor"
    dataset_snapshot_id: int
    run_type: str = "walk_forward"
    train_start: date | None = None; train_end: date | None = None
    valid_start: date | None = None; valid_end: date | None = None
    test_start: date | None = None; test_end: date | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    split_config: dict[str, Any] = Field(default_factory=lambda:{"train_years":3,"valid_months":3,"test_months":3,"prediction_horizon":5,"embargo_days":2})
    feature_config: dict[str, Any] = Field(default_factory=lambda:{"ablation":"all_features","base":"Alpha158"})
    target_config: dict[str, Any] = Field(default_factory=lambda:{"benchmark":"sector_or_qqq","entry":"T+1 open","exit":"T+5 close"})


class PublishRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class IntradayRunRequest(BaseModel):
    trade_date: date | None = None

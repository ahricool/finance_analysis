"""Quant API write contracts."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetBuildRequest(BaseModel):
    market: Literal["US", "CN"] = "US"
    universe: str | None = None
    date_from: date
    date_to: date


class WalkForwardSplitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train_years: int = Field(3, ge=1)
    valid_months: int = Field(3, ge=1)
    test_months: int = Field(3, ge=1)
    retrain_frequency_months: int = Field(3, ge=1)
    prediction_horizon: int = Field(5, ge=1)
    embargo_days: int = Field(2, ge=0)


class TrainingFeatureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: Literal["Alpha158"] = "Alpha158"


class TrainingTargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_horizon: int = Field(5, ge=1)
    benchmark: Literal[
        "sector_or_market",
        "sector_or_qqq",
        "market",
        "sector",
        "none",
    ] = "sector_or_market"
    entry_price: Literal["open", "close"] = "open"
    exit_price: Literal["open", "close"] = "close"
    excess_return: bool = True


class ModelRunCreateRequest(BaseModel):
    model_key: Literal["cross_section_lgbm", "time_series_lgbm"] = "cross_section_lgbm"
    model_version: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    market: Literal["US", "CN"] = "US"
    universe: str | None = None
    dataset_snapshot_id: int
    run_type: str = "walk_forward"
    train_start: date | None = None
    train_end: date | None = None
    valid_start: date | None = None
    valid_end: date | None = None
    test_start: date | None = None
    test_end: date | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    split_config: WalkForwardSplitConfig = Field(default_factory=WalkForwardSplitConfig)
    feature_config: TrainingFeatureConfig = Field(default_factory=TrainingFeatureConfig)
    target_config: TrainingTargetConfig = Field(default_factory=TrainingTargetConfig)

    @model_validator(mode="after")
    def matching_prediction_horizons(self):
        if self.target_config.prediction_horizon != self.split_config.prediction_horizon:
            raise ValueError("target_config and split_config prediction_horizon must match")
        return self


class PublishRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class IntradayRunRequest(BaseModel):
    trade_date: date | None = None

"""Quant API write contracts."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from finance_analysis.quant.targets import production_target_config  # pragma: allowlist secret


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


class ModelRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: Literal["cross_section_lgbm", "time_series_lgbm"] = "cross_section_lgbm"
    model_version: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    market: Literal["US", "CN"] = "US"
    universe: str | None = None
    dataset_snapshot_id: int
    run_type: str = "walk_forward"
    parameters: dict[str, Any] = Field(default_factory=dict)
    split_config: WalkForwardSplitConfig = Field(default_factory=WalkForwardSplitConfig)
    feature_config: TrainingFeatureConfig = Field(default_factory=TrainingFeatureConfig)

    def stored_target_config(self) -> dict[str, Any]:
        return production_target_config(self.model_key, self.split_config.prediction_horizon)


class PublishRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)

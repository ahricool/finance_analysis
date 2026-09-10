"""Versioned JSON-only task protocol shared by all Qlib task handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = 1


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return dict(value)


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_schema(payload: Mapping[str, Any]) -> None:
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_base(payload: Mapping[str, Any]) -> None:
    _validate_schema(payload)
    _positive_int(payload.get("model_run_id"), "model_run_id")


def _model_ref(raw: Any, name: str) -> "ModelArtifactRef":
    payload = _mapping(raw, name)
    return ModelArtifactRef(
        model_run_id=_positive_int(payload.get("model_run_id"), f"{name}.model_run_id"),
        model_key=_required_string(payload, "model_key"),
        artifact_uri=_required_string(payload, "artifact_uri"),
    )


@dataclass(frozen=True)
class TrainPayload:
    schema_version: int
    model_run_id: int
    dataset_uri: str
    model_key: str
    model_version: str
    parameters: dict[str, Any] = field(default_factory=dict)
    feature_config: dict[str, Any] = field(default_factory=dict)
    target_config: dict[str, Any] = field(default_factory=dict)
    split_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "TrainPayload":
        _validate_base(payload)
        return cls(
            schema_version=SCHEMA_VERSION,
            model_run_id=int(payload["model_run_id"]),
            dataset_uri=_required_string(payload, "dataset_uri"),
            model_key=_required_string(payload, "model_key"),
            model_version=_required_string(payload, "model_version"),
            parameters=_mapping(payload.get("parameters"), "parameters"),
            feature_config=_mapping(payload.get("feature_config"), "feature_config"),
            target_config=_mapping(payload.get("target_config"), "target_config"),
            split_config=_mapping(payload.get("split_config"), "split_config"),
        )


@dataclass(frozen=True)
class PredictPayload:
    schema_version: int
    model_run_id: int
    artifact_uri: str
    dataset_uri: str
    trade_date: str
    model_key: str

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "PredictPayload":
        _validate_base(payload)
        return cls(
            schema_version=SCHEMA_VERSION,
            model_run_id=int(payload["model_run_id"]),
            artifact_uri=_required_string(payload, "artifact_uri"),
            dataset_uri=_required_string(payload, "dataset_uri"),
            trade_date=_required_string(payload, "trade_date"),
            model_key=_required_string(payload, "model_key"),
        )


@dataclass(frozen=True)
class ModelArtifactRef:
    model_run_id: int
    model_key: str
    artifact_uri: str


@dataclass(frozen=True)
class DailyPredictPayload:
    schema_version: int
    dataset_uri: str
    trade_date: str
    cross_section: ModelArtifactRef
    time_series: ModelArtifactRef

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "DailyPredictPayload":
        _validate_schema(payload)
        cross_section = _model_ref(payload.get("cross_section"), "cross_section")
        time_series = _model_ref(payload.get("time_series"), "time_series")
        if cross_section.model_key != "cross_section_lgbm":
            raise ValueError("cross_section.model_key must be cross_section_lgbm")
        if time_series.model_key != "time_series_lgbm":
            raise ValueError("time_series.model_key must be time_series_lgbm")
        return cls(
            schema_version=SCHEMA_VERSION,
            dataset_uri=_required_string(payload, "dataset_uri"),
            trade_date=_required_string(payload, "trade_date"),
            cross_section=cross_section,
            time_series=time_series,
        )


@dataclass(frozen=True)
class ArtifactPayload:
    schema_version: int
    model_run_id: int
    artifact_uri: str

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "ArtifactPayload":
        _validate_base(payload)
        return cls(
            schema_version=SCHEMA_VERSION,
            model_run_id=int(payload["model_run_id"]),
            artifact_uri=_required_string(payload, "artifact_uri"),
        )

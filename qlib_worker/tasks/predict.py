"""Qlib model prediction tasks."""

from __future__ import annotations

import json
import logging
from typing import Any

import joblib
import pandas as pd

from qlib_worker.artifacts import ArtifactStore
from qlib_worker.celery_app import celery_app
from qlib_worker.config import get_worker_config
from qlib_worker.datasets import load_features, load_manifest
from qlib_worker.models.base import BaseLGBMRunner
from qlib_worker.models.registry import get_runner
from qlib_worker.protocol import DailyPredictPayload, ModelArtifactRef, PredictPayload
from qlib_worker.price_modes import require_forward_adjusted_manifest

logger = logging.getLogger(__name__)


def _load_bundle(store: ArtifactStore, spec: ModelArtifactRef | PredictPayload) -> dict[str, Any]:
    artifact = store.path_for_uri(spec.artifact_uri)
    metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("model_key") != spec.model_key:
        raise ValueError("Prediction model_key does not match artifact metadata")
    return {
        "bundle": joblib.load(artifact / "model.joblib"),
        "metadata": metadata,
        "runner": get_runner(spec.model_key),
    }


def _rows_for_trade_date(features: pd.DataFrame, manifest: dict[str, Any], trade_date: str) -> pd.DataFrame:
    target_date = pd.Timestamp(trade_date)
    rows = features[features.index.get_level_values("datetime") == target_date].copy()
    symbols = manifest.get("symbols")
    if not isinstance(symbols, list) or not symbols or not all(isinstance(code, str) for code in symbols):
        raise ValueError("Prediction dataset manifest symbols must be a non-empty string list")
    expected_codes = set(symbols)
    rows = rows[rows.index.get_level_values("instrument").isin(expected_codes)]
    if rows.empty:
        raise ValueError(f"No prediction features for trade_date {trade_date}")
    actual_codes = list(rows.index.get_level_values("instrument"))
    missing_codes = sorted(expected_codes - set(actual_codes))
    duplicate_codes = sorted(code for code in set(actual_codes) if actual_codes.count(code) > 1)
    if missing_codes or duplicate_codes or len(actual_codes) != len(expected_codes):
        raise ValueError(
            f"Prediction feature coverage mismatch for {trade_date}: "
            f"expected={len(expected_codes)} actual={len(actual_codes)} "
            f"missing={missing_codes} duplicates={duplicate_codes}"
        )
    return rows


def _predict_frame(runner: BaseLGBMRunner, bundle: dict[str, Any], rows: pd.DataFrame) -> pd.DataFrame:
    columns = list(bundle["columns"])
    raw = pd.Series(runner.predict(bundle["model"], rows, columns, bundle["medians"]), index=rows.index)
    result = pd.DataFrame(
        {
            "code": rows.index.get_level_values("instrument"),
            "raw_prediction": raw.to_numpy(),
            "normalized_score": runner.normalized_score(raw).to_numpy(),
        }
    )
    result["universe_rank"] = result["raw_prediction"].rank(method="first", ascending=False).astype(int)
    result["predicted_return"] = result["raw_prediction"]
    return result


def _predict_one(
    store: ArtifactStore,
    spec: ModelArtifactRef | PredictPayload,
    dataset_price_mode: str,
    rows: pd.DataFrame,
    trade_date: str,
) -> dict[str, Any]:
    loaded = _load_bundle(store, spec)
    model_price_mode = loaded["metadata"].get("price_mode")
    if model_price_mode != dataset_price_mode:
        raise ValueError(
            "Model and prediction dataset price_mode mismatch: "
            f"model={model_price_mode!r} dataset={dataset_price_mode!r}"
        )
    result = _predict_frame(loaded["runner"], loaded["bundle"], rows)
    return {
        "schema_version": 1,
        "model_run_id": spec.model_run_id,
        "model_key": spec.model_key,
        "trade_date": trade_date,
        "predictions": result.to_dict("records"),
    }


@celery_app.task(name="qlib.model.predict", bind=True)
def predict_model(self: Any, **raw_payload: Any) -> dict[str, Any]:
    payload = PredictPayload.parse(raw_payload)
    task_id = str(self.request.id)
    logger.info(
        "Qlib prediction started task_id=%s model_run_id=%s artifact_uri=%s",
        task_id,
        payload.model_run_id,
        payload.artifact_uri,
    )
    try:
        store = ArtifactStore(get_worker_config().artifact_root)
        dataset = store.path_for_uri(payload.dataset_uri)
        manifest = load_manifest(dataset)
        dataset_price_mode = require_forward_adjusted_manifest(manifest)
        features = load_features(dataset, manifest, {"base": "Alpha158"})
        rows = _rows_for_trade_date(features, manifest, payload.trade_date)
        return _predict_one(store, payload, dataset_price_mode, rows, payload.trade_date)
    except Exception:
        logger.exception(
            "Qlib prediction failed task_id=%s model_run_id=%s artifact_uri=%s",
            task_id,
            payload.model_run_id,
            payload.artifact_uri,
        )
        raise


@celery_app.task(name="qlib.daily.predict", bind=True)
def predict_daily(self: Any, **raw_payload: Any) -> dict[str, Any]:
    payload = DailyPredictPayload.parse(raw_payload)
    task_id = str(self.request.id)
    logger.info(
        "Qlib daily prediction started task_id=%s trade_date=%s dataset_uri=%s",
        task_id,
        payload.trade_date,
        payload.dataset_uri,
    )
    try:
        store = ArtifactStore(get_worker_config().artifact_root)
        dataset = store.path_for_uri(payload.dataset_uri)
        manifest = load_manifest(dataset)
        dataset_price_mode = require_forward_adjusted_manifest(manifest)
        features = load_features(dataset, manifest, {"base": "Alpha158"})
        rows = _rows_for_trade_date(features, manifest, payload.trade_date)
        results = [
            _predict_one(store, payload.cross_section, dataset_price_mode, rows, payload.trade_date),
            _predict_one(store, payload.time_series, dataset_price_mode, rows, payload.trade_date),
        ]
        return {
            "schema_version": 1,
            "trade_date": payload.trade_date,
            "results": results,
        }
    except Exception:
        logger.exception(
            "Qlib daily prediction failed task_id=%s trade_date=%s dataset_uri=%s",
            task_id,
            payload.trade_date,
            payload.dataset_uri,
        )
        raise

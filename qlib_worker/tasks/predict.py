"""Qlib model prediction task."""

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
from qlib_worker.models.registry import get_runner
from qlib_worker.protocol import PredictPayload
from qlib_worker.price_modes import require_forward_adjusted_manifest

logger = logging.getLogger(__name__)


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
        artifact = store.path_for_uri(payload.artifact_uri)
        dataset = store.path_for_uri(payload.dataset_uri)
        metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("model_key") != payload.model_key:
            raise ValueError("Prediction model_key does not match artifact metadata")
        runner = get_runner(payload.model_key)
        bundle = joblib.load(artifact / "model.joblib")
        manifest = load_manifest(dataset)
        dataset_price_mode = require_forward_adjusted_manifest(manifest)
        model_price_mode = metadata.get("price_mode")
        if model_price_mode != dataset_price_mode:
            raise ValueError(
                "Model and prediction dataset price_mode mismatch: "
                f"model={model_price_mode!r} dataset={dataset_price_mode!r}"
            )
        features = load_features(dataset, manifest, metadata.get("feature_config", {}))
        target_date = pd.Timestamp(payload.trade_date)
        rows = features[features.index.get_level_values("datetime") == target_date].copy()
        if rows.empty:
            raise ValueError(f"No prediction features for trade_date {payload.trade_date}")
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
        return {
            "schema_version": 1,
            "model_run_id": payload.model_run_id,
            "model_key": payload.model_key,
            "trade_date": payload.trade_date,
            "predictions": result.to_dict("records"),
        }
    except Exception:
        logger.exception(
            "Qlib prediction failed task_id=%s model_run_id=%s artifact_uri=%s",
            task_id,
            payload.model_run_id,
            payload.artifact_uri,
        )
        raise

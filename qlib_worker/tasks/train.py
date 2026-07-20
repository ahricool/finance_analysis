"""Qlib model training task."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

import qlib

from qlib_worker.artifacts import ArtifactStore
from qlib_worker.celery_app import celery_app
from qlib_worker.config import get_worker_config
from qlib_worker.datasets import load_features, load_manifest
from qlib_worker.models.registry import get_runner
from qlib_worker.models.splits import WalkForwardConfig
from qlib_worker.models.targets import TargetConfig, build_target
from qlib_worker.models.training import train_walk_forward
from qlib_worker.protocol import TrainPayload

logger = logging.getLogger(__name__)


@celery_app.task(name="qlib.model.train", bind=True)
def train_model(self: Any, **raw_payload: Any) -> dict[str, Any]:
    payload = TrainPayload.parse(raw_payload)
    task_id = str(self.request.id)
    store = ArtifactStore(get_worker_config().artifact_root)
    artifact_uri = store.model_uri(payload.model_key, payload.model_version, payload.model_run_id)
    logger.info(
        "Qlib training started task_id=%s model_run_id=%s artifact_uri=%s",
        task_id,
        payload.model_run_id,
        artifact_uri,
    )
    try:
        runner = get_runner(payload.model_key)
        dataset = store.path_for_uri(payload.dataset_uri)
        manifest = load_manifest(dataset)
        split_config = WalkForwardConfig.parse(payload.split_config)
        target_config = TargetConfig.parse(payload.target_config, split_config.prediction_horizon)
        if target_config.prediction_horizon != split_config.prediction_horizon:
            raise ValueError("target_config prediction_horizon must equal split_config prediction_horizon")
        request_payload = asdict(payload)
        request_digest = store.request_digest(request_payload)

        def write(output: Any) -> dict[str, Any]:
            features = load_features(dataset, manifest, payload.feature_config)
            target = build_target(dataset, manifest, target_config)
            panel = features.join(target.rename("label"), how="inner")
            training = train_walk_forward(
                panel,
                runner,
                payload.parameters,
                split_config,
                output,
                {
                    "dataset_uri": payload.dataset_uri,
                    "model_key": payload.model_key,
                    "runner": runner.name,
                    "runner_version": runner.version,
                },
            )
            metadata = {
                **request_payload,
                "runner": runner.name,
                "runner_version": runner.version,
                "qlib_version": qlib.__version__,
                "actual_parameters": training["actual_parameters"],
                "target_config": asdict(target_config),
                "split_config": training["split_config"],
                "final_training_strategy": training["final_training_strategy"],
                "final_training_end": training["final_training_end"],
            }
            (output / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
            return {
                "schema_version": 1,
                "model_run_id": payload.model_run_id,
                "model_key": payload.model_key,
                "metrics": training["metrics"],
                "feature_importance": training["feature_importance"],
                "warnings": manifest.get("warnings", []),
            }

        result = store.commit_model(artifact_uri, request_digest, write)
        logger.info("Qlib training completed task_id=%s model_run_id=%s", task_id, payload.model_run_id)
        return result
    except Exception:
        logger.exception(
            "Qlib training failed task_id=%s model_run_id=%s artifact_uri=%s",
            task_id,
            payload.model_run_id,
            artifact_uri,
        )
        raise

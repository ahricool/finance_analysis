from __future__ import annotations

from typing import Any

from qlib_worker.artifacts import ArtifactStore
from qlib_worker.celery_app import celery_app
from qlib_worker.config import get_worker_config
from qlib_worker.datasets.validator import validate_dataset
from qlib_worker.protocol import ArtifactPayload


@celery_app.task(name="qlib.dataset.validate")
def validate_dataset_task(**raw_payload: Any) -> dict[str, Any]:
    payload = ArtifactPayload.parse(raw_payload)
    store = ArtifactStore(get_worker_config().artifact_root)
    return {
        "schema_version": 1,
        "model_run_id": payload.model_run_id,
        **validate_dataset(store.path_for_uri(payload.artifact_uri)),
    }


@celery_app.task(name="qlib.artifact.inspect")
def inspect_artifact(**raw_payload: Any) -> dict[str, Any]:
    payload = ArtifactPayload.parse(raw_payload)
    store = ArtifactStore(get_worker_config().artifact_root)
    return {"schema_version": 1, "model_run_id": payload.model_run_id, **store.inspect(payload.artifact_uri)}

"""Non-blocking Qlib training dispatch and business-database callbacks."""

from __future__ import annotations

from typing import Any

from finance_analysis.quant.exceptions import UnsupportedUniverseError, TrainingAlreadyStartedError
from finance_analysis.quant.pipeline.service import QuantTrainingPipeline
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS, QUEUE_QLIB
from finance_analysis.tasks.lifecycle import (track_task, defer_task_completion, get_current_task_id,
    get_task_lifecycle_service, TaskLifecycleMetadata)


@celery_app.task(name="quant.model.train")
@track_task(
    task_type="quant_training",
    task_name="训练量化模型",
    source="celery_manual",
    uid_getter=lambda model_run_id, owner_uid=None, **_: owner_uid,
    record_result=True,
)
def train_quant_model(model_run_id: int, owner_uid: int | None = None, **_: Any) -> dict[str, Any]:
    parent_id = get_current_task_id()
    pipeline = QuantTrainingPipeline()
    try:
        payload = pipeline.prepare(model_run_id)
        result = celery_app.send_task(
            "qlib.model.train",
            kwargs=payload,
            queue=QUEUE_QLIB,
            headers={"_skip_task_record": True},
            link=finalize_quant_model.s(model_run_id=model_run_id, parent_id=parent_id, owner_uid=owner_uid).set(queue=QUEUE_ANALYSIS),
            link_error=fail_quant_model.s(model_run_id=model_run_id, parent_id=parent_id, owner_uid=owner_uid).set(queue=QUEUE_ANALYSIS),
        )
        pipeline.mark_dispatched(model_run_id, result.id)
        return defer_task_completion({"model_run_id": model_run_id, "qlib_task_id": result.id, "status": "training"})
    except (UnsupportedUniverseError, TrainingAlreadyStartedError):
        # A deprecated run is historical data. Record the Celery task failure,
        # but never rewrite the historical model-run status or artifacts.
        raise
    except Exception as exc:
        pipeline.fail(model_run_id, str(exc))
        raise


def _finish_training(parent_id, owner_uid, result=None, error=None):
    if not parent_id:
        return
    service = get_task_lifecycle_service()
    metadata = TaskLifecycleMetadata(task_type="quant_training", task_name="训练量化模型",
                                     source="celery_manual", uid=owner_uid)
    if error:
        service.mark_failed(task_id=parent_id, metadata=metadata, error=error, message=str(error)[:200])
    else:
        service.mark_completed(task_id=parent_id, metadata=metadata, result=result, message="训练完成，等待发布")


@celery_app.task(name="quant.model.train.finalize", bind=True, max_retries=3)
def finalize_quant_model(self, result: dict[str, Any], model_run_id: int,
                         parent_id=None, owner_uid=None) -> dict[str, Any]:
    try:
        finalized = QuantTrainingPipeline().finalize(model_run_id, result)
        _finish_training(parent_id, owner_uid, result=finalized)
        return finalized
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
        QuantTrainingPipeline().fail(model_run_id, str(exc))
        _finish_training(parent_id, owner_uid, error=exc)
        raise


@celery_app.task(name="quant.model.train.failed")
def fail_quant_model(failed_task_id: str, *, model_run_id: int,
                     parent_id=None, owner_uid=None) -> dict[str, Any]:
    detail = celery_app.AsyncResult(failed_task_id).result
    reason = f"Qlib task {failed_task_id} failed: {detail or 'unknown error'}"
    pipeline = QuantTrainingPipeline()
    run = pipeline.repository.get_model_run(model_run_id)
    if run and run.status in {"candidate", "production", "retired"}:
        return {"model_run_id": model_run_id, "status": run.status}
    result = pipeline.fail(model_run_id, reason)
    _finish_training(parent_id, owner_uid, error=RuntimeError(reason))
    return result


@celery_app.task(name="quant.experiment.prepare")
@track_task(task_type="quant_training", task_name="准备量化训练实验", source="celery_manual",
            uid_getter=lambda run_ids, owner_uid=None, **_: owner_uid, record_result=True)
def prepare_quant_experiment(run_ids: list[int], owner_uid: int | None = None, **_: Any):
    from finance_analysis.database.repositories.quant import QuantRepository
    from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
    from finance_analysis.quant.training import training_preflight
    repo = QuantRepository()
    first = repo.get_model_run(run_ids[0])
    if first is None or any(repo.get_model_run(key).status != "draft" for key in run_ids):
        raise ValueError("Experiment has already started or no longer exists")
    try:
        training_preflight(repo, first.market, first.train_start, first.train_end)
        universe = repo.get_universe(first.universe_id)
        dataset = QlibDatasetExporter(repo).export(first.market, universe.key, first.train_start, first.train_end)
        for run_id in run_ids:
            if not repo.update_model_run(run_id, expected_statuses={"draft"}, dataset_snapshot_id=dataset.id):
                continue
            train_quant_model.apply_async(kwargs={"model_run_id": run_id, "owner_uid": owner_uid}, queue=QUEUE_ANALYSIS)
        return {"model_run_ids": run_ids, "status": "training_submitted"}
    except Exception as exc:
        for run_id in run_ids:
            run = repo.get_model_run(run_id)
            if run.status == "draft":
                QuantTrainingPipeline(repo).fail(run_id, str(exc))
        raise

"""Non-blocking Qlib training dispatch and business-database callbacks."""

from __future__ import annotations

from typing import Any

from finance_analysis.quant.exceptions import UnsupportedQuantUniverseError
from finance_analysis.quant.pipeline.service import QuantTrainingPipeline
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS, QUEUE_QLIB
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name="quant.model.train")
@track_task(
    task_type="quant_training",
    task_name="训练量化模型",
    source="celery_manual",
    uid_getter=lambda model_run_id, owner_uid=None, **_: owner_uid,
    record_result=True,
)
def train_quant_model(model_run_id: int, owner_uid: int | None = None, **_: Any) -> dict[str, Any]:
    del owner_uid
    pipeline = QuantTrainingPipeline()
    try:
        payload = pipeline.prepare(model_run_id)
        result = celery_app.send_task(
            "qlib.model.train",
            kwargs=payload,
            queue=QUEUE_QLIB,
            link=finalize_quant_model.s(model_run_id=model_run_id).set(queue=QUEUE_ANALYSIS),
            link_error=fail_quant_model.s(model_run_id=model_run_id).set(queue=QUEUE_ANALYSIS),
        )
        pipeline.mark_dispatched(model_run_id, result.id)
        return {"model_run_id": model_run_id, "qlib_task_id": result.id, "status": "training"}
    except UnsupportedQuantUniverseError:
        # A deprecated run is historical data. Record the Celery task failure,
        # but never rewrite the historical model-run status or artifacts.
        raise
    except Exception as exc:
        pipeline.fail(model_run_id, str(exc))
        raise


@celery_app.task(name="quant.model.train.finalize")
def finalize_quant_model(result: dict[str, Any], model_run_id: int) -> dict[str, Any]:
    return QuantTrainingPipeline().finalize(model_run_id, result)


@celery_app.task(name="quant.model.train.failed")
def fail_quant_model(failed_task_id: str, model_run_id: int) -> dict[str, Any]:
    async_result = celery_app.AsyncResult(failed_task_id)
    detail = async_result.result
    reason = f"Qlib task {failed_task_id} failed"
    if detail:
        reason = f"{reason}: {detail}"
    return QuantTrainingPipeline().fail(model_run_id, reason)

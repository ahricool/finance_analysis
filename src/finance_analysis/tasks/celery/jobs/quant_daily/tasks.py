"""Non-blocking daily Qlib fan-out and main-application chord callback."""

from __future__ import annotations

from typing import Any

from celery import chord

from finance_analysis.quant.pipeline.service import QuantDailyPipeline
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS, QUEUE_QLIB
from finance_analysis.tasks.celery.schedule.constants import (
    JOB_QUANT_DAILY_PIPELINE_CN,
    JOB_QUANT_DAILY_PIPELINE_US,
)
from finance_analysis.tasks.lifecycle import (
    TaskLifecycleMetadata,
    defer_task_completion,
    get_current_task_id,
    get_task_lifecycle_service,
    track_task,
)


def _lifecycle_metadata(context: dict[str, Any]) -> TaskLifecycleMetadata:
    market = str(context.get("market") or "").upper()
    is_cn = market == "CN"
    return TaskLifecycleMetadata(
        task_type="scheduled_quant_daily_cn" if is_cn else "scheduled_quant_daily_us",
        task_name="A股量化日频流水线" if is_cn else "美股量化日频流水线",
        source="celery_schedule",
        scheduler_job_id=JOB_QUANT_DAILY_PIPELINE_CN if is_cn else JOB_QUANT_DAILY_PIPELINE_US,
    )


def _mark_final_status(
    context: dict[str, Any],
    result: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    task_id = context.get("lifecycle_task_id")
    if not task_id:
        return
    service = get_task_lifecycle_service()
    metadata = _lifecycle_metadata(context)
    if error is not None:
        service.mark_failed(
            task_id=str(task_id),
            metadata=metadata,
            error=error,
            message=str(error)[:200],
        )
        return
    skipped_members = int(((result or {}).get("coverage") or {}).get("skipped_members") or 0)
    service.mark_completed(
        task_id=str(task_id),
        metadata=metadata,
        result=result,
        message="任务完成，已跳过部分缺失行情标的" if skipped_members else "任务执行完成",
    )


def _dispatch(market: str) -> dict[str, Any]:
    requests, context = QuantDailyPipeline().prepare(market=market)
    lifecycle_task_id = get_current_task_id()
    if lifecycle_task_id:
        context["lifecycle_task_id"] = lifecycle_task_id
    header = [celery_app.signature("qlib.model.predict", kwargs=payload, queue=QUEUE_QLIB) for payload in requests]
    callback = finalize_quant_daily.s(context=context, _skip_task_record=True).set(queue=QUEUE_ANALYSIS)
    error_callback = fail_quant_daily.s(context=context, _skip_task_record=True).set(queue=QUEUE_ANALYSIS)
    result = chord(header).apply_async(body=callback, link_error=error_callback)
    return {
        "status": "prediction_dispatched",
        "trade_date": context["trade_date"],
        "chord_task_id": result.id,
        "qlib_task_count": len(header),
        "market": context["market"],
        "universe": context["universe_key"],
    }


@celery_app.task(name="scheduled.quant_daily_pipeline_us")
@track_task(
    task_type="scheduled_quant_daily_us",
    task_name="美股量化日频流水线",
    source="celery_schedule",
    record_result=True,
)
def quant_daily_pipeline_us(**_: Any) -> Any:
    return defer_task_completion(_dispatch("US"))


@celery_app.task(name="scheduled.quant_daily_pipeline_cn")
@track_task(
    task_type="scheduled_quant_daily_cn",
    task_name="A股量化日频流水线",
    source="celery_schedule",
    record_result=True,
)
def quant_daily_pipeline_cn(**_: Any) -> Any:
    return defer_task_completion(_dispatch("CN"))


@celery_app.task(name="quant.daily.finalize")
def finalize_quant_daily(
    results: list[dict[str, Any]], context: dict[str, Any], _skip_task_record: bool = False
) -> dict[str, Any]:
    del _skip_task_record
    try:
        result = QuantDailyPipeline().finalize(results, context)
    except Exception as exc:
        _mark_final_status(context, error=exc)
        raise
    _mark_final_status(context, result=result)
    return result


@celery_app.task(name="quant.daily.failed")
def fail_quant_daily(
    failed_task_id: str, context: dict[str, Any], _skip_task_record: bool = False
) -> dict[str, Any]:
    del _skip_task_record
    detail = celery_app.AsyncResult(failed_task_id).result
    result = {
        "status": "failed",
        "trade_date": context.get("trade_date"),
        "market": context.get("market"),
        "universe": context.get("universe_key"),
        "failed_task_id": failed_task_id,
        "error": str(detail) if detail else "Qlib prediction task failed",
    }
    _mark_final_status(context, error=RuntimeError(result["error"]))
    return result

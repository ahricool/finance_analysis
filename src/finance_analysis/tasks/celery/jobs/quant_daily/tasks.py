"""Non-blocking daily Qlib prediction and main-application callback."""

from __future__ import annotations

from typing import Any
import logging

from finance_analysis.quant.pipeline.service import QuantDailyPipeline
from finance_analysis.quant.datasets.transient import PredictionInputs
from finance_analysis.quant.datasets.cleanup import cleanup_inputs
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.core.time import utc_now
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS, QUEUE_QLIB
from finance_analysis.tasks.celery.schedule.constants import (
    JOB_QUANT_DAILY_PIPELINE_CN,
    JOB_QUANT_DAILY_PIPELINE_US,
)
from finance_analysis.tasks.lifecycle import (
    TaskLifecycleMetadata,
    TaskSkipped,
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


def _discard_input(context: dict[str, Any]) -> bool:
    try:
        return PredictionInputs().remove(context.get("input_uri"))
    except OSError:
        logging.getLogger(__name__).exception("Temporary input cleanup deferred to startup or maintenance")
        return False


def _dispatch(market: str) -> dict[str, Any]:
    try:
        cleanup_inputs(dry_run=False)
    except OSError:
        logging.getLogger(__name__).exception("Startup cleanup deferred to maintenance; daily prediction continues")
    from finance_analysis.market_review.trading_calendar import get_market_now, is_market_session_closed
    calendar_market = market.lower()
    market_now = get_market_now(calendar_market)
    if not is_market_session_closed(calendar_market, current_time=market_now):
        raise TaskSkipped("当前不是已收盘交易日，不重复生成历史批次")
    lifecycle_task_id = get_current_task_id()
    payload, context = QuantDailyPipeline().prepare(market=market, task_id=lifecycle_task_id)
    if lifecycle_task_id:
        context["lifecycle_task_id"] = lifecycle_task_id
    try:
        result = celery_app.send_task(
            "qlib.daily.predict",
            kwargs=payload,
            # The tracked parent remains processing until the DB-owning callback finishes.
            headers={"_skip_task_record": True},
            queue=QUEUE_QLIB,
            link=finalize_quant_daily.s(context=context, _skip_task_record=True).set(queue=QUEUE_ANALYSIS),
            link_error=fail_quant_daily.s(context=context, _skip_task_record=True).set(queue=QUEUE_ANALYSIS),
        )
    except Exception as exc:
        QuantRepository().update_execution(context["execution_id"], status="failed", error=str(exc)[:4000], finished_at=utc_now())
        _discard_input(context)
        raise
    return {
        "status": "prediction_dispatched",
        "trade_date": context["trade_date"],
        "qlib_task_id": result.id,
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


@celery_app.task(name="quant.daily.finalize", bind=True, max_retries=3)
def finalize_quant_daily(
    self, result: dict[str, Any], context: dict[str, Any], _skip_task_record: bool = False
) -> dict[str, Any]:
    del _skip_task_record
    try:
        finalized = QuantDailyPipeline().finalize(result, context)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
        removed = _discard_input(context)
        QuantRepository().update_execution(
            context["execution_id"], status="failed", error=str(exc)[:4000], finished_at=utc_now(),
            input_uri=None if removed else context.get("input_uri"),
        )
        _mark_final_status(context, error=exc)
        raise
    _mark_final_status(context, result=finalized)
    _discard_input(context)
    return finalized


@celery_app.task(name="quant.daily.failed")
def fail_quant_daily(
    failed_task_id: str, *, context: dict[str, Any], _skip_task_record: bool = False
) -> dict[str, Any]:
    del _skip_task_record
    execution = QuantRepository().execution(context["execution_id"])
    if execution and execution.status == "complete":
        return {"status": "complete", "execution_id": execution.id}
    detail = celery_app.AsyncResult(failed_task_id).result
    result = {
        "status": "failed",
        "trade_date": context.get("trade_date"),
        "market": context.get("market"),
        "universe": context.get("universe_key"),
        "failed_task_id": failed_task_id,
        "error": str(detail) if detail else "Qlib prediction task failed",
    }
    removed = _discard_input(context)
    QuantRepository().update_execution(
        context["execution_id"], status="failed", error=result["error"], finished_at=utc_now(),
        input_uri=None if removed else context.get("input_uri"),
    )
    _mark_final_status(context, error=RuntimeError(result["error"]))
    return result


@celery_app.task(name="scheduled.quant_cleanup")
@track_task(task_type="scheduled_quant_cleanup", task_name="清理量化临时输入", source="celery_schedule", record_result=True)
def cleanup_quant_inputs(**_):
    return cleanup_inputs(dry_run=False)

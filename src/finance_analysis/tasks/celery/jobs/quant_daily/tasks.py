"""Non-blocking daily Qlib fan-out and main-application chord callback."""

from __future__ import annotations

from typing import Any

from celery import chord

from finance_analysis.quant.pipeline.service import QuantDailyPipeline
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS, QUEUE_QLIB
from finance_analysis.tasks.lifecycle import track_task


def _dispatch(market: str) -> dict[str, Any]:
    requests, context = QuantDailyPipeline().prepare(market=market)
    header = [celery_app.signature("qlib.model.predict", kwargs=payload, queue=QUEUE_QLIB) for payload in requests]
    callback = finalize_quant_daily.s(context=context).set(queue=QUEUE_ANALYSIS)
    error_callback = fail_quant_daily.s(context=context).set(queue=QUEUE_ANALYSIS)
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
def quant_daily_pipeline_us(**_: Any) -> dict[str, Any]:
    return _dispatch("US")


@celery_app.task(name="scheduled.quant_daily_pipeline_cn")
@track_task(
    task_type="scheduled_quant_daily_cn",
    task_name="A股量化日频流水线",
    source="celery_schedule",
    record_result=True,
)
def quant_daily_pipeline_cn(**_: Any) -> dict[str, Any]:
    return _dispatch("CN")


@celery_app.task(name="quant.daily.finalize")
def finalize_quant_daily(results: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    return QuantDailyPipeline().finalize(results, context)


@celery_app.task(name="quant.daily.failed")
def fail_quant_daily(failed_task_id: str, context: dict[str, Any]) -> dict[str, Any]:
    detail = celery_app.AsyncResult(failed_task_id).result
    return {
        "status": "failed",
        "trade_date": context.get("trade_date"),
        "market": context.get("market"),
        "universe": context.get("universe_key"),
        "failed_task_id": failed_task_id,
        "error": str(detail) if detail else "Qlib prediction task failed",
    }

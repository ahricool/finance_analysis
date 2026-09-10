"""Thin Celery entry points for the shared ETF momentum rotation engine."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from finance_analysis.etf_rotation.service import ETFRotationService  # pragma: allowlist secret
from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open  # pragma: allowlist secret
from finance_analysis.tasks.celery.app import celery_app  # pragma: allowlist secret
from finance_analysis.tasks.celery.schedule import (  # pragma: allowlist secret
    JOB_ETF_ROTATION_CN,
    JOB_ETF_ROTATION_PREVIEW_CN,
    JOB_ETF_ROTATION_PREVIEW_US,
    JOB_ETF_ROTATION_US,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import TaskSkipped, track_task  # pragma: allowlist secret

CN_DEFINITION = require_scheduled_task_definition(JOB_ETF_ROTATION_CN)
US_DEFINITION = require_scheduled_task_definition(JOB_ETF_ROTATION_US)
CN_PREVIEW_DEFINITION = require_scheduled_task_definition(JOB_ETF_ROTATION_PREVIEW_CN)
US_PREVIEW_DEFINITION = require_scheduled_task_definition(JOB_ETF_ROTATION_PREVIEW_US)

PREVIEW_TASK_RESULT_KEYS = (
    "status",
    "market",
    "trade_date",
    "preview_time",
    "provider",
    "quote_count",
    "universe_size",
    "data_coverage",
    "rankable_count",
    "rankable_coverage",
    "snapshot_count",
    "candidate_count",
    "candidate_codes",
    "regime",
    "warnings",
    "elapsed_seconds",
)


def _preview_task_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in PREVIEW_TASK_RESULT_KEYS if key in result}


def _run_preview(market: str, trade_date: str | None) -> dict[str, Any]:
    requested = date.fromisoformat(trade_date) if trade_date else get_market_now(market.lower()).date()
    if not is_market_open(market.lower(), requested):
        raise TaskSkipped(f"{market} 当天不是交易日，跳过 ETF 轮动预演")
    result = ETFRotationService(market).run_preview(requested)
    if result.get("status") != "completed":
        details = {
            key: result[key]
            for key in ("trade_date", "status", "warnings", "data_coverage", "provider", "quote_count")
            if key in result
        }
        details["market"] = market
        raise RuntimeError(
            "ETF Rotation preview did not complete: " + json.dumps(details, ensure_ascii=False, default=str)
        )
    return _preview_task_result(result)


@celery_app.task(name=CN_DEFINITION.celery_task_name)
@track_task(
    task_type=CN_DEFINITION.task_type,
    task_name=CN_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN_DEFINITION.job_id,
    record_result=True,
    success_message="A股 ETF 动量轮动完成",
    strip_lifecycle_kwargs=True,
)
def run_etf_rotation_cn(
    scheduler_job_id: Optional[str] = None,
    trade_date: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    requested = date.fromisoformat(trade_date) if trade_date else None
    return ETFRotationService("CN").run(requested)


@celery_app.task(name=US_DEFINITION.celery_task_name)
@track_task(
    task_type=US_DEFINITION.task_type,
    task_name=US_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=US_DEFINITION.job_id,
    record_result=True,
    success_message="美股 ETF 动量轮动完成",
    strip_lifecycle_kwargs=True,
)
def run_etf_rotation_us(
    scheduler_job_id: Optional[str] = None,
    trade_date: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    requested = date.fromisoformat(trade_date) if trade_date else None
    return ETFRotationService("US").run(requested)


@celery_app.task(name=CN_PREVIEW_DEFINITION.celery_task_name)
@track_task(
    task_type=CN_PREVIEW_DEFINITION.task_type,
    task_name=CN_PREVIEW_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN_PREVIEW_DEFINITION.job_id,
    record_result=True,
    success_message="A股 ETF 动量轮动盘中预演完成",
    strip_lifecycle_kwargs=True,
)
def run_etf_rotation_preview_cn(
    scheduler_job_id: Optional[str] = None,
    trade_date: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    return _run_preview("CN", trade_date)


@celery_app.task(name=US_PREVIEW_DEFINITION.celery_task_name)
@track_task(
    task_type=US_PREVIEW_DEFINITION.task_type,
    task_name=US_PREVIEW_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=US_PREVIEW_DEFINITION.job_id,
    record_result=True,
    success_message="美股 ETF 动量轮动盘中预演完成",
    strip_lifecycle_kwargs=True,
)
def run_etf_rotation_preview_us(
    scheduler_job_id: Optional[str] = None,
    trade_date: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    return _run_preview("US", trade_date)


__all__ = [
    "run_etf_rotation_cn",
    "run_etf_rotation_preview_cn",
    "run_etf_rotation_preview_us",
    "run_etf_rotation_us",
]

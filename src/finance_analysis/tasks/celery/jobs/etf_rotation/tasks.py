"""Thin Celery entry points for the shared ETF momentum rotation engine."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from finance_analysis.etf_rotation.service import ETFRotationService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import (
    JOB_ETF_ROTATION_CN,
    JOB_ETF_ROTATION_US,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import track_task

CN_DEFINITION = require_scheduled_task_definition(JOB_ETF_ROTATION_CN)
US_DEFINITION = require_scheduled_task_definition(JOB_ETF_ROTATION_US)


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
    dedupe_key=f"scheduled:{CN_DEFINITION.job_id}",
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
    dedupe_key=f"scheduled:{US_DEFINITION.job_id}",
)
def run_etf_rotation_us(
    scheduler_job_id: Optional[str] = None,
    trade_date: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    requested = date.fromisoformat(trade_date) if trade_date else None
    return ETFRotationService("US").run(requested)


__all__ = ["run_etf_rotation_cn", "run_etf_rotation_us"]

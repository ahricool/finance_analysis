"""Celery entry point for the A-share ETF momentum rotation."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from finance_analysis.etf_rotation.service import ETFRotationService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import JOB_ETF_ROTATION_CN, require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task

DEFINITION = require_scheduled_task_definition(JOB_ETF_ROTATION_CN)


@celery_app.task(name=DEFINITION.celery_task_name)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    success_message="A股 ETF 动量轮动完成",
    strip_lifecycle_kwargs=True,
    dedupe_key=f"scheduled:{DEFINITION.job_id}",
)
def run_etf_rotation_cn(
    scheduler_job_id: Optional[str] = None,
    trade_date: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    requested = date.fromisoformat(trade_date) if trade_date else None
    return ETFRotationService().run(requested)


__all__ = ["run_etf_rotation_cn"]

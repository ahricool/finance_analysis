"""Celery entry point for market-calendar synchronization."""

from __future__ import annotations

from typing import Any, Optional

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import (
    JOB_MARKET_CALENDAR,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import track_task

from .service import MarketCalendarSyncTaskService

DEFINITION = require_scheduled_task_definition(JOB_MARKET_CALENDAR)


@celery_app.task(name=DEFINITION.celery_task_name)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    success_message="定时任务执行完成",
    strip_lifecycle_kwargs=True,
)
def market_calendar(scheduler_job_id: Optional[str] = None, **_: Any) -> dict[str, Any]:
    return MarketCalendarSyncTaskService().run()


__all__ = ["market_calendar"]

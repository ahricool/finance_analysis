"""Celery entry points for database-only Trend Following calculations."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import (
    JOB_TREND_FOLLOWING_CN,
    JOB_TREND_FOLLOWING_US,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import track_task
from finance_analysis.trend_following.service import TrendFollowingService

CN_DEFINITION = require_scheduled_task_definition(JOB_TREND_FOLLOWING_CN)
US_DEFINITION = require_scheduled_task_definition(JOB_TREND_FOLLOWING_US)


@celery_app.task(name=CN_DEFINITION.celery_task_name)
@track_task(
    task_type=CN_DEFINITION.task_type, task_name=CN_DEFINITION.name, source="celery",
    trigger_source="scheduler", scheduler_job_id=CN_DEFINITION.job_id, record_result=True,
    success_message="A股趋势跟踪计算完成", strip_lifecycle_kwargs=True,
)
def run_trend_following_cn(
    scheduler_job_id: Optional[str] = None, trade_date: str | None = None, **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    return TrendFollowingService("CN").run(date.fromisoformat(trade_date) if trade_date else None)


@celery_app.task(name=US_DEFINITION.celery_task_name)
@track_task(
    task_type=US_DEFINITION.task_type, task_name=US_DEFINITION.name, source="celery",
    trigger_source="scheduler", scheduler_job_id=US_DEFINITION.job_id, record_result=True,
    success_message="美股趋势跟踪计算完成", strip_lifecycle_kwargs=True,
)
def run_trend_following_us(
    scheduler_job_id: Optional[str] = None, trade_date: str | None = None, **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    return TrendFollowingService("US").run(date.fromisoformat(trade_date) if trade_date else None)


__all__ = ["run_trend_following_cn", "run_trend_following_us"]

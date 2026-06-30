"""Independent Celery entry point for A-share signal evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from finance_analysis.analysis.signal_evaluation import SignalEvaluationService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import (
    JOB_SIGNAL_EVALUATION_CN,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import track_task

DEFINITION = require_scheduled_task_definition(JOB_SIGNAL_EVALUATION_CN)


@celery_app.task(name=DEFINITION.celery_task_name)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    success_message="A股信号评价完成",
    strip_lifecycle_kwargs=True,
)
def evaluate_signals_cn(scheduler_job_id: Optional[str] = None, **_: Any) -> dict[str, Any]:
    now = datetime.now(ZoneInfo(DEFINITION.timezone))
    return SignalEvaluationService().evaluate_signals(market="CN", now=now)


__all__ = ["evaluate_signals_cn"]

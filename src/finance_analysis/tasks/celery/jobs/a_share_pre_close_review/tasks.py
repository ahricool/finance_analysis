"""Celery entry point for the A-share pre-close review."""

from __future__ import annotations

from typing import Any, Optional

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import (
    JOB_A_SHARE_PRE_CLOSE_REVIEW,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import track_task

from .service import ASharePreCloseReviewService

DEFINITION = require_scheduled_task_definition(JOB_A_SHARE_PRE_CLOSE_REVIEW)


@celery_app.task(name=DEFINITION.celery_task_name)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    success_message="A股收盘前复核完成",
    strip_lifecycle_kwargs=True,
)
def analysis_a_share_pre_close_review(
    scheduler_job_id: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    return ASharePreCloseReviewService().run().to_task_result_dict()


__all__ = ["analysis_a_share_pre_close_review"]

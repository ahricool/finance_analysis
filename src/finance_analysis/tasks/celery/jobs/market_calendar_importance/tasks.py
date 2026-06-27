"""Celery entry point for market-calendar importance scoring."""

from __future__ import annotations

from typing import Any, Sequence

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.metadata import MARKET_CALENDAR_IMPORTANCE_TASK
from finance_analysis.tasks.lifecycle import track_task

from .service import MarketCalendarImportanceTaskService


@celery_app.task(name=MARKET_CALENDAR_IMPORTANCE_TASK.celery_name)
@track_task(
    task_type=MARKET_CALENDAR_IMPORTANCE_TASK.task_type,
    task_name=MARKET_CALENDAR_IMPORTANCE_TASK.display_name,
    source=MARKET_CALENDAR_IMPORTANCE_TASK.source,
    record_result=True,
    success_message="重要性评分完成",
)
def market_calendar_importance(event_ids: Sequence[int]) -> dict[str, Any]:
    return MarketCalendarImportanceTaskService().run(event_ids)


__all__ = ["market_calendar_importance"]

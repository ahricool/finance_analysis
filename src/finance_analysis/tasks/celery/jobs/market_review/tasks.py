"""Celery entry point for market review."""

from __future__ import annotations

from typing import Any, Dict, Optional

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.metadata import MARKET_REVIEW_TASK
from finance_analysis.tasks.lifecycle import track_task

from .service import MarketReviewTaskService


@celery_app.task(name=MARKET_REVIEW_TASK.celery_name)
@track_task(
    task_type=MARKET_REVIEW_TASK.task_type,
    task_name=MARKET_REVIEW_TASK.display_name,
    source=MARKET_REVIEW_TASK.source,
    record_result=True,
    success_message="任务执行完成",
)
def run_market_review(
    *,
    task_id: str,
    send_notification: bool,
    override_region: Optional[str] = None,
    bot_message: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return MarketReviewTaskService().run(
        send_notification=send_notification,
        override_region=override_region,
        bot_message=bot_message,
    )


__all__ = ["run_market_review"]

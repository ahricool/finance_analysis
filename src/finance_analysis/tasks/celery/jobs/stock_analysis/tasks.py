"""Celery entry point for single-stock analysis."""

from __future__ import annotations

from typing import Any, Dict, Optional

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.metadata import STOCK_ANALYSIS_TASK
from finance_analysis.tasks.lifecycle import track_task

from .service import StockAnalysisTaskService


def _task_display_name(**kwargs: Any) -> str:
    return f"{STOCK_ANALYSIS_TASK.display_name} {kwargs.get('stock_code') or ''}".strip()


@celery_app.task(name=STOCK_ANALYSIS_TASK.celery_name)
@track_task(
    task_type=STOCK_ANALYSIS_TASK.task_type,
    task_name=STOCK_ANALYSIS_TASK.display_name,
    source=STOCK_ANALYSIS_TASK.source,
    uid_getter=lambda **kwargs: kwargs.get("owner_uid"),
    task_name_getter=_task_display_name,
    success_message="分析完成",
)
def run_stock_analysis(
    *,
    task_id: str,
    stock_code: str,
    report_type: str = "detailed",
    force_refresh: bool = False,
    notify: bool = True,
    owner_uid: Optional[int] = None,
    task_source: str = "api",
    bot_message: Optional[Dict[str, Any]] = None,
    save_context_snapshot: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    return StockAnalysisTaskService().run(
        task_id=task_id,
        stock_code=stock_code,
        report_type=report_type,
        force_refresh=force_refresh,
        notify=notify,
        owner_uid=owner_uid,
        task_source=task_source,
        bot_message=bot_message,
        save_context_snapshot=save_context_snapshot,
    )


__all__ = ["run_stock_analysis"]

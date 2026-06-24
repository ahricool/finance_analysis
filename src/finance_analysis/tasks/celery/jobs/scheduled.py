# -*- coding: utf-8 -*-
"""Celery tasks for the code-defined periodic jobs.

Each task is intentionally thin: it accepts the scheduling context delivered by
Beat (or a manual submission), delegates to the matching plain business runner
in :mod:`finance_analysis.tasks.scheduled_jobs`, and relies on
:func:`finance_analysis.tasks.lifecycle.track_task` for the full TaskRecord
lifecycle (pending → processing → completed/failed/skipped) plus failure
notifications. No market-data, news, LLM, or database analysis runs here
directly.
"""

from __future__ import annotations

from typing import Any, Optional

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import (
    JOB_A_SHARE_INTRADAY_ANALYSIS,
    JOB_DAILY_ANALYSIS,
    JOB_MARKET_CALENDAR,
    JOB_US_INTRADAY_ANALYSIS,
    JOB_US_POSTMARKET_REVIEW,
    JOB_US_PREMARKET_ANALYSIS,
    JOB_US_PREMARKET_NEWS,
    celery_task_name,
)
from finance_analysis.tasks import scheduled_jobs
from finance_analysis.tasks.lifecycle import track_task

_SUCCESS_MESSAGE = "定时任务执行完成"


@celery_app.task(name=celery_task_name(JOB_DAILY_ANALYSIS))
@track_task(
    task_type="scheduled_daily",
    task_name="每日全量分析",
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=JOB_DAILY_ANALYSIS,
    record_result=True,
    success_message=_SUCCESS_MESSAGE,
    strip_lifecycle_kwargs=True,
)
def analysis_daily(scheduler_job_id: Optional[str] = None, **_: Any) -> None:
    return scheduled_jobs.run_daily_analysis()


@celery_app.task(name=celery_task_name(JOB_MARKET_CALENDAR))
@track_task(
    task_type="scheduled_market_calendar",
    task_name="美股财经日历同步",
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=JOB_MARKET_CALENDAR,
    record_result=True,
    success_message=_SUCCESS_MESSAGE,
    strip_lifecycle_kwargs=True,
)
def market_calendar(scheduler_job_id: Optional[str] = None, **_: Any) -> None:
    return scheduled_jobs.run_market_calendar()


@celery_app.task(name=celery_task_name(JOB_US_PREMARKET_NEWS))
@track_task(
    task_type="scheduled_us_premarket_news",
    task_name="美股盘前新闻情报",
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=JOB_US_PREMARKET_NEWS,
    record_result=True,
    success_message=_SUCCESS_MESSAGE,
    strip_lifecycle_kwargs=True,
)
def analysis_us_premarket_news(scheduler_job_id: Optional[str] = None, **_: Any) -> None:
    return scheduled_jobs.run_us_premarket_news()


@celery_app.task(name=celery_task_name(JOB_US_PREMARKET_ANALYSIS))
@track_task(
    task_type="scheduled_us_premarket",
    task_name="美股盘前分析",
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=JOB_US_PREMARKET_ANALYSIS,
    record_result=True,
    success_message=_SUCCESS_MESSAGE,
    strip_lifecycle_kwargs=True,
)
def analysis_us_premarket(scheduler_job_id: Optional[str] = None, **_: Any) -> None:
    return scheduled_jobs.run_us_premarket_analysis()


@celery_app.task(name=celery_task_name(JOB_US_INTRADAY_ANALYSIS))
@track_task(
    task_type="scheduled_us_intraday",
    task_name="美股盘中分析",
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=JOB_US_INTRADAY_ANALYSIS,
    record_result=True,
    success_message=_SUCCESS_MESSAGE,
    strip_lifecycle_kwargs=True,
)
def analysis_us_intraday(scheduler_job_id: Optional[str] = None, **_: Any) -> None:
    return scheduled_jobs.run_us_intraday_analysis()


@celery_app.task(name=celery_task_name(JOB_US_POSTMARKET_REVIEW))
@track_task(
    task_type="scheduled_us_postmarket_review",
    task_name="美股收盘复盘",
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=JOB_US_POSTMARKET_REVIEW,
    record_result=True,
    success_message=_SUCCESS_MESSAGE,
    strip_lifecycle_kwargs=True,
)
def analysis_us_postmarket_review(scheduler_job_id: Optional[str] = None, **_: Any) -> dict:
    return scheduled_jobs.run_us_postmarket_review()


@celery_app.task(name=celery_task_name(JOB_A_SHARE_INTRADAY_ANALYSIS))
@track_task(
    task_type="scheduled_a_share_intraday",
    task_name="A股盘中分析",
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=JOB_A_SHARE_INTRADAY_ANALYSIS,
    record_result=True,
    success_message=_SUCCESS_MESSAGE,
    strip_lifecycle_kwargs=True,
)
def analysis_a_share_intraday(scheduler_job_id: Optional[str] = None, **_: Any) -> dict:
    return scheduled_jobs.run_a_share_intraday_analysis()


# Map job_id -> Celery task object for manual submission via apply_async.
SCHEDULED_CELERY_TASKS = {
    JOB_DAILY_ANALYSIS: analysis_daily,
    JOB_MARKET_CALENDAR: market_calendar,
    JOB_US_PREMARKET_NEWS: analysis_us_premarket_news,
    JOB_US_PREMARKET_ANALYSIS: analysis_us_premarket,
    JOB_US_INTRADAY_ANALYSIS: analysis_us_intraday,
    JOB_US_POSTMARKET_REVIEW: analysis_us_postmarket_review,
    JOB_A_SHARE_INTRADAY_ANALYSIS: analysis_a_share_intraday,
}


def get_scheduled_celery_task(job_id: str):
    """Return the Celery task object bound to ``job_id`` (or ``None``)."""
    return SCHEDULED_CELERY_TASKS.get(job_id)


__all__ = [
    "SCHEDULED_CELERY_TASKS",
    "analysis_a_share_intraday",
    "analysis_daily",
    "analysis_us_intraday",
    "analysis_us_postmarket_review",
    "analysis_us_premarket",
    "analysis_us_premarket_news",
    "get_scheduled_celery_task",
    "market_calendar",
]

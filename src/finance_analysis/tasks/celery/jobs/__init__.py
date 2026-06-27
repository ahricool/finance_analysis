# -*- coding: utf-8 -*-
"""Explicit task packages loaded by the Celery application."""

TASK_PACKAGES = (
    "finance_analysis.tasks.celery.jobs.demo_add",
    "finance_analysis.tasks.celery.jobs.stock_analysis",
    "finance_analysis.tasks.celery.jobs.market_review",
    "finance_analysis.tasks.celery.jobs.market_calendar_importance",
    "finance_analysis.tasks.celery.jobs.daily_analysis",
    "finance_analysis.tasks.celery.jobs.market_calendar_sync",
    "finance_analysis.tasks.celery.jobs.us_premarket_news",
    "finance_analysis.tasks.celery.jobs.us_premarket_analysis",
    "finance_analysis.tasks.celery.jobs.us_intraday_analysis",
    "finance_analysis.tasks.celery.jobs.us_postmarket_review",
    "finance_analysis.tasks.celery.jobs.a_share_intraday_analysis",
)
TASK_MODULES = tuple(f"{package}.tasks" for package in TASK_PACKAGES)

__all__ = ["TASK_MODULES", "TASK_PACKAGES"]

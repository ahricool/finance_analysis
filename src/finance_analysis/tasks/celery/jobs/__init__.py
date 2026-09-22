# -*- coding: utf-8 -*-
"""Explicit task packages loaded by the Celery application."""

TASK_PACKAGES = (
    "finance_analysis.tasks.celery.jobs.intraday_confirmation",
    "finance_analysis.tasks.celery.jobs.dragon_tiger_flow",
    "finance_analysis.tasks.celery.jobs.confluence",
    "finance_analysis.tasks.celery.jobs.signal_center",
    "finance_analysis.tasks.celery.jobs.crypto_strategy",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.market_sentiment",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.industry_strength",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.market_structure",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.demo_add",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.stock_analysis",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.market_review",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.market_calendar_importance",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.daily_analysis",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.market_calendar_sync",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.us_premarket_news",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.us_premarket_analysis",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.us_postmarket_review",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.market_data_sync",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.reference_data_sync",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.a_share_pre_close_review",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.quant_dataset",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.quant_training",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.quant_daily",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.etf_rotation",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.trend_following",  # pragma: allowlist secret
    "finance_analysis.tasks.celery.jobs.trade_engine",  # pragma: allowlist secret
)
TASK_MODULES = tuple(f"{package}.tasks" for package in TASK_PACKAGES)

__all__ = ["TASK_MODULES", "TASK_PACKAGES"]

# -*- coding: utf-8 -*-
"""Queue, timezone, expiry, and stable job identifiers."""

QUEUE_ALERTS = "alerts"
QUEUE_ANALYSIS = "analysis"
QUEUE_INGESTION = "ingestion"
QUEUE_MAINTENANCE = "maintenance"
QUEUE_DEFAULT = "celery"

ALL_QUEUES = (
    QUEUE_ALERTS,
    QUEUE_ANALYSIS,
    QUEUE_INGESTION,
    QUEUE_MAINTENANCE,
    QUEUE_DEFAULT,
)

SCHEDULE_TIMEZONE = "Asia/Shanghai"
US_TIMEZONE = "America/New_York"

EXPIRES_INTRADAY = 4 * 60
EXPIRES_PREMARKET = 30 * 60
EXPIRES_NEWS = 30 * 60
EXPIRES_CALENDAR = 60 * 60
EXPIRES_POSTMARKET_REVIEW = 90 * 60
EXPIRES_DAILY = 6 * 60 * 60

JOB_DAILY_ANALYSIS = "analysis_daily"
JOB_MARKET_CALENDAR = "market_calendar"
JOB_US_PREMARKET_NEWS = "analysis_us_premarket_news"
JOB_US_PREMARKET_ANALYSIS = "analysis_us_premarket"
JOB_US_INTRADAY_ANALYSIS = "analysis_us_intraday"
JOB_US_POSTMARKET_REVIEW = "analysis_us_postmarket_review"
JOB_A_SHARE_INTRADAY_ANALYSIS = "analysis_a_share_intraday"


def celery_task_name(job_id: str) -> str:
    return f"scheduled.{job_id}"

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
EXPIRES_SIGNAL_EVALUATION = 60 * 60
EXPIRES_MARKET_DATA_SYNC = 6 * 60 * 60
EXPIRES_QUANT = 6 * 60 * 60

JOB_DAILY_ANALYSIS = "analysis_daily"
JOB_MARKET_CALENDAR = "market_calendar"
JOB_US_PREMARKET_NEWS = "analysis_us_premarket_news"
JOB_US_PREMARKET_ANALYSIS = "analysis_us_premarket"
JOB_US_INTRADAY_ANALYSIS = "analysis_us_intraday"
JOB_US_POSTMARKET_REVIEW = "analysis_us_postmarket_review"
JOB_US_MARKET_DATA_SYNC = "market_data_sync_us"
JOB_A_SHARE_INTRADAY_ANALYSIS = "analysis_a_share_intraday"
JOB_SIGNAL_EVALUATION_CN = "signal_evaluation_cn"
JOB_SIGNAL_EVALUATION_US = "signal_evaluation_us"
JOB_QUANT_DAILY_PIPELINE_US = "quant_daily_pipeline_us"
JOB_QUANT_MODEL_TRAINING_US = "quant_model_training_us"


def celery_task_name(job_id: str) -> str:
    return f"scheduled.{job_id}"

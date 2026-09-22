# -*- coding: utf-8 -*-
"""Queue, timezone, expiry, and stable job identifiers."""

QUEUE_ALERTS = "alerts"
QUEUE_ANALYSIS = "analysis"
QUEUE_INGESTION = "ingestion"
QUEUE_MAINTENANCE = "maintenance"
QUEUE_DEFAULT = "celery"
QUEUE_QLIB = "qlib"

ALL_QUEUES = (
    QUEUE_ALERTS,
    QUEUE_ANALYSIS,
    QUEUE_INGESTION,
    QUEUE_MAINTENANCE,
    QUEUE_DEFAULT,
    QUEUE_QLIB,
)

SCHEDULE_TIMEZONE = "Asia/Shanghai"
US_TIMEZONE = "America/New_York"

EXPIRES_INTRADAY = 4 * 60
EXPIRES_PREMARKET = 30 * 60
EXPIRES_NEWS = 30 * 60
EXPIRES_CALENDAR = 60 * 60
EXPIRES_POSTMARKET_REVIEW = 90 * 60
EXPIRES_PRE_CLOSE_REVIEW = 30 * 60
EXPIRES_DAILY = 6 * 60 * 60
EXPIRES_MARKET_DATA_SYNC = 6 * 60 * 60
EXPIRES_QUANT = 6 * 60 * 60
EXPIRES_ETF_ROTATION = 2 * 60 * 60
EXPIRES_ETF_ROTATION_PREVIEW = 60 * 60
EXPIRES_TREND_FOLLOWING = 3 * 60 * 60
EXPIRES_TREND_FOLLOWING_PREVIEW = 60 * 60

JOB_CRYPTO_BTC_STRATEGY = "crypto_btc_strategy"
JOB_DAILY_ANALYSIS = "analysis_daily"
JOB_MARKET_CALENDAR = "market_calendar"
JOB_US_PREMARKET_NEWS = "analysis_us_premarket_news"
JOB_US_PREMARKET_ANALYSIS = "analysis_us_premarket"
JOB_US_POSTMARKET_REVIEW = "analysis_us_postmarket_review"
JOB_REFERENCE_DATA_SYNC = "reference_data_sync"
JOB_MARKET_DATA_SYNC_CN = "market_data_sync_cn"
JOB_MARKET_DATA_SYNC_US = "market_data_sync_us"
JOB_A_SHARE_PRE_CLOSE_REVIEW = "analysis_a_share_pre_close_review"
JOB_QUANT_DAILY_PIPELINE_US = "quant_daily_pipeline_us"
JOB_QUANT_DAILY_PIPELINE_CN = "quant_daily_pipeline_cn"
JOB_INDUSTRY_STRENGTH_PREVIEW_CN = "industry_strength_preview_cn"
JOB_INDUSTRY_STRENGTH_CN = "industry_strength_cn"
JOB_MARKET_STRUCTURE_CN = "market_structure_cn"
JOB_MARKET_STRUCTURE_US = "market_structure_us"
JOB_ETF_ROTATION_CN = "etf_rotation_cn"
JOB_ETF_ROTATION_US = "etf_rotation_us"
JOB_ETF_ROTATION_PREVIEW_CN = "etf_rotation_preview_cn"
JOB_ETF_ROTATION_PREVIEW_US = "etf_rotation_preview_us"
JOB_TREND_FOLLOWING_CN = "trend_following_cn"
JOB_TREND_FOLLOWING_US = "trend_following_us"
JOB_TREND_FOLLOWING_PREVIEW_CN = "trend_following_preview_cn"
JOB_TREND_FOLLOWING_PREVIEW_US = "trend_following_preview_us"
JOB_TRADE_ENGINE_CN = "trade_engine_cn"
JOB_TRADE_ENGINE_US = "trade_engine_us"

EXPIRES_TRADE_ENGINE = 20 * 60


def celery_task_name(job_id: str) -> str:
    return f"scheduled.{job_id}"


JOB_MARKET_SENTIMENT_CN = "market_sentiment_cn"

JOB_DRAGON_TIGER_FLOW_CN = "dragon_tiger_flow_cn"
JOB_CONFLUENCE_CN = "confluence_cn"
JOB_CONFLUENCE_US = "confluence_us"

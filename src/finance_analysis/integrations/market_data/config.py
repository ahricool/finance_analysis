# -*- coding: utf-8 -*-
"""Market data provider configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging

from finance_analysis.config.env_parsing import env_bool, env_int, env_str

logger = logging.getLogger(__name__)


def _resolve_realtime_source_priority(tushare_token: str | None) -> str:
    default_priority = "tencent,akshare_sina,efinance,akshare_em"
    if (tushare_token or "").strip():
        resolved = f"tushare,{default_priority}"
        logger.info("TUSHARE_TOKEN detected, auto-injecting tushare into realtime priority: %s", resolved)
        return resolved
    return default_priority


@dataclass
class DataProviderConfig:
    tushare_token: str | None = None
    tickflow_api_key: str | None = None
    longbridge_app_key: str | None = None
    longbridge_app_secret: str | None = None
    longbridge_access_token: str | None = None
    prefetch_realtime_quotes: bool = True
    enable_realtime_quote: bool = True
    enable_realtime_technical_indicators: bool = True
    enable_chip_distribution: bool = True
    enable_eastmoney_patch: bool = False
    realtime_source_priority: str = "tencent,akshare_sina,efinance,akshare_em"
    enable_fundamental_pipeline: bool = True
    fundamental_stage_timeout_seconds: float = 1.5
    fundamental_fetch_timeout_seconds: float = 0.8
    fundamental_retry_max: int = 1
    fundamental_cache_ttl_seconds: int = 120
    fundamental_cache_max_entries: int = 256
    market_data_initial_daily_days: int = 3 * 365
    market_data_initial_minute_days: int = 3
    market_data_repair_daily_days: int = 14
    market_data_repair_minute_days: int = 3
    market_data_longbridge_max_concurrency: int = 5
    market_data_longbridge_max_retries: int = 3
    market_data_yfinance_max_concurrency: int = 3
    market_data_yfinance_max_retries: int = 2


@lru_cache(maxsize=1)
def get_data_provider_config() -> DataProviderConfig:
    tushare_token = env_str("TUSHARE_TOKEN") or None
    return DataProviderConfig(
        tushare_token=tushare_token,
        tickflow_api_key=env_str("TICKFLOW_API_KEY") or None,
        longbridge_app_key=env_str("LONGBRIDGE_APP_KEY") or None,
        longbridge_app_secret=env_str("LONGBRIDGE_APP_SECRET") or None,
        longbridge_access_token=env_str("LONGBRIDGE_ACCESS_TOKEN") or None,
        enable_eastmoney_patch=env_bool("ENABLE_EASTMONEY_PATCH", False),
        realtime_source_priority=_resolve_realtime_source_priority(tushare_token),
        market_data_initial_daily_days=env_int("MARKET_DATA_INITIAL_DAILY_DAYS", 3 * 365, minimum=1),
        market_data_initial_minute_days=env_int("MARKET_DATA_INITIAL_MINUTE_DAYS", 3, minimum=1),
        market_data_repair_daily_days=env_int("MARKET_DATA_REPAIR_DAILY_DAYS", 14, minimum=1),
        market_data_repair_minute_days=env_int("MARKET_DATA_REPAIR_MINUTE_DAYS", 3, minimum=1),
        market_data_longbridge_max_concurrency=env_int(
            "MARKET_DATA_LONGBRIDGE_MAX_CONCURRENCY", 5, minimum=1, maximum=5
        ),
        market_data_longbridge_max_retries=env_int("MARKET_DATA_LONGBRIDGE_MAX_RETRIES", 3, minimum=0),
        market_data_yfinance_max_concurrency=env_int(
            "MARKET_DATA_YFINANCE_MAX_CONCURRENCY", 3, minimum=1
        ),
        market_data_yfinance_max_retries=env_int("MARKET_DATA_YFINANCE_MAX_RETRIES", 2, minimum=0),
    )

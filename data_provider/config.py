# -*- coding: utf-8 -*-
"""Market data provider configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging

from src.utils.env import env_bool, env_float, env_int, env_str

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
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
    realtime_cache_ttl: int = 600
    circuit_breaker_cooldown: int = 300
    enable_fundamental_pipeline: bool = True
    fundamental_stage_timeout_seconds: float = 1.5
    fundamental_fetch_timeout_seconds: float = 0.8
    fundamental_retry_max: int = 1
    fundamental_cache_ttl_seconds: int = 120
    fundamental_cache_max_entries: int = 256


def _resolve_realtime_source_priority() -> str:
    explicit = env_str("REALTIME_SOURCE_PRIORITY")
    default_priority = "tencent,akshare_sina,efinance,akshare_em"
    if explicit:
        return explicit
    if (env_str("TUSHARE_TOKEN", "") or "").strip():
        resolved = f"tushare,{default_priority}"
        logger.info("TUSHARE_TOKEN detected, auto-injecting tushare into realtime priority: %s", resolved)
        return resolved
    return default_priority


@lru_cache(maxsize=1)
def get_data_provider_config() -> DataProviderConfig:
    return DataProviderConfig(
        tushare_token=env_str("TUSHARE_TOKEN") or None,
        tickflow_api_key=env_str("TICKFLOW_API_KEY") or None,
        longbridge_app_key=env_str("LONGBRIDGE_APP_KEY") or None,
        longbridge_app_secret=env_str("LONGBRIDGE_APP_SECRET") or None,
        longbridge_access_token=env_str("LONGBRIDGE_ACCESS_TOKEN") or None,
        prefetch_realtime_quotes=env_bool("PREFETCH_REALTIME_QUOTES", True),
        enable_realtime_quote=env_bool("ENABLE_REALTIME_QUOTE", True),
        enable_realtime_technical_indicators=env_bool("ENABLE_REALTIME_TECHNICAL_INDICATORS", True),
        enable_chip_distribution=env_bool("ENABLE_CHIP_DISTRIBUTION", True),
        enable_eastmoney_patch=env_bool("ENABLE_EASTMONEY_PATCH", False),
        realtime_source_priority=_resolve_realtime_source_priority(),
        realtime_cache_ttl=env_int("REALTIME_CACHE_TTL", 600, minimum=0),
        circuit_breaker_cooldown=env_int("CIRCUIT_BREAKER_COOLDOWN", 300, minimum=0),
        enable_fundamental_pipeline=env_bool("ENABLE_FUNDAMENTAL_PIPELINE", True),
        fundamental_stage_timeout_seconds=env_float("FUNDAMENTAL_STAGE_TIMEOUT_SECONDS", 1.5, minimum=0.0),
        fundamental_fetch_timeout_seconds=env_float("FUNDAMENTAL_FETCH_TIMEOUT_SECONDS", 0.8, minimum=0.0),
        fundamental_retry_max=env_int("FUNDAMENTAL_RETRY_MAX", 1, minimum=0),
        fundamental_cache_ttl_seconds=env_int("FUNDAMENTAL_CACHE_TTL_SECONDS", 120, minimum=0),
        fundamental_cache_max_entries=env_int("FUNDAMENTAL_CACHE_MAX_ENTRIES", 256, minimum=1),
    )

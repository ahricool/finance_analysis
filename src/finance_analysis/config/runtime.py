# -*- coding: utf-8 -*-
"""Process/runtime settings that do not belong to a business domain."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging

from finance_analysis.config.env_parsing import env_bool, env_int, env_list, env_str

logger = logging.getLogger(__name__)


def _parse_market_review_region(value: str | None) -> str:
    candidate = (value or "cn").strip().lower()
    if candidate in {"cn", "us", "hk", "both"}:
        return candidate
    logger.warning("MARKET_REVIEW_REGION=%r is invalid; falling back to 'cn'", value)
    return "cn"


@dataclass(frozen=True)
class RuntimeConfig:
    log_dir: str = "./logs"
    log_level: str = "INFO"
    max_workers: int = 3
    market_review_enabled: bool = True
    market_review_region: str = "cn"
    trading_day_check_enabled: bool = True
    webui_enabled: bool = False
    webui_host: str = "0.0.0.0"
    webui_port: int = 8000
    secret_key: str = ""
    bot_enabled: bool = True
    bot_command_prefix: str = "/"
    bot_rate_limit_requests: int = 10
    bot_rate_limit_window: int = 60
    bot_admin_users: list[str] | None = None
    social_sentiment_api_key: str | None = None
    social_sentiment_api_url: str = "https://api.adanos.org"

    def __post_init__(self) -> None:
        if self.bot_admin_users is None:
            object.__setattr__(self, "bot_admin_users", [])


@lru_cache(maxsize=1)
def get_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        log_dir=env_str("LOG_DIR", "./logs") or "./logs",
        log_level=env_str("LOG_LEVEL", "INFO") or "INFO",
        max_workers=env_int("MAX_WORKERS", 3, minimum=1),
        market_review_enabled=env_bool("MARKET_REVIEW_ENABLED", True),
        market_review_region=_parse_market_review_region(env_str("MARKET_REVIEW_REGION", "cn")),
        trading_day_check_enabled=env_bool("TRADING_DAY_CHECK_ENABLED", True),
        webui_enabled=env_bool("WEBUI_ENABLED", False),
        webui_host=env_str("WEBUI_HOST") or env_str("API_HOST") or "0.0.0.0",
        webui_port=env_int("WEBUI_PORT", env_int("API_PORT", 8000, minimum=1, maximum=65535), minimum=1, maximum=65535),
        secret_key=env_str("SECRET_KEY", "") or "",
        bot_enabled=env_bool("BOT_ENABLED", True),
        bot_command_prefix=env_str("BOT_COMMAND_PREFIX", "/") or "/",
        bot_rate_limit_requests=env_int("BOT_RATE_LIMIT_REQUESTS", 10, minimum=1),
        bot_rate_limit_window=env_int("BOT_RATE_LIMIT_WINDOW", 60, minimum=1),
        bot_admin_users=env_list("BOT_ADMIN_USERS"),
        social_sentiment_api_key=env_str("SOCIAL_SENTIMENT_API_KEY") or None,
        social_sentiment_api_url=(env_str("SOCIAL_SENTIMENT_API_URL", "https://api.adanos.org") or "https://api.adanos.org").rstrip("/"),
    )

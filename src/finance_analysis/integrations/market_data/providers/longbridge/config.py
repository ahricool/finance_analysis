"""Shared Longbridge runtime and SDK configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import inspect
import logging
import os
from typing import Any, Dict

from finance_analysis.config.env_parsing import env_bool, env_int, env_str
from finance_analysis.core.paths import get_log_app_dir

logger = logging.getLogger(__name__)

_DEFAULT_STATIC_INFO_TTL = 86400
_DEFAULT_CONNECTION_COOLDOWN_SECONDS = 15

_REGION_URL_MAP: Dict[str, Dict[str, str]] = {
    "cn": {
        "http_url": "https://openapi.longbridge.cn",
        "quote_ws_url": "wss://openapi-quote.longbridge.cn/v2",
        "trade_ws_url": "wss://openapi-trade.longbridge.cn/v2",
    },
    "hk": {
        "http_url": "https://openapi.longbridge.com",
        "quote_ws_url": "wss://openapi-quote.longbridge.com/v2",
        "trade_ws_url": "wss://openapi-trade.longbridge.com/v2",
    },
}


def sanitize_longbridge_env() -> None:
    """Normalize Longbridge environment variables for SDK compatibility."""
    for key in (
        "LONGBRIDGE_HTTP_URL",
        "LONGBRIDGE_QUOTE_WS_URL",
        "LONGBRIDGE_TRADE_WS_URL",
        "LONGBRIDGE_ENABLE_OVERNIGHT",
        "LONGBRIDGE_PUSH_CANDLESTICK_MODE",
        "LONGBRIDGE_PRINT_QUOTE_PACKAGES",
        "LONGBRIDGE_REGION",
        "LONGBRIDGE_STATIC_INFO_TTL_SECONDS",
        "LONGBRIDGE_LOG_PATH",
    ):
        value = os.environ.get(key)
        if value is not None and value.strip() == "":
            del os.environ[key]
            logger.debug("[Longbridge] 删除空环境变量 %s", key)

    if "LONGBRIDGE_PRINT_QUOTE_PACKAGES" not in os.environ:
        os.environ["LONGBRIDGE_PRINT_QUOTE_PACKAGES"] = "false"

    if not os.environ.get("LONGBRIDGE_LOG_PATH"):
        try:
            log_dir = get_log_app_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            os.environ["LONGBRIDGE_LOG_PATH"] = str(log_dir / "longbridge_sdk.log")
            logger.debug("[Longbridge] 设置 LONGBRIDGE_LOG_PATH=%s", os.environ["LONGBRIDGE_LOG_PATH"])
        except Exception:
            pass

    region = (os.getenv("LONGBRIDGE_REGION") or "").strip().lower()
    if region:
        if not os.environ.get("LONGPORT_REGION"):
            os.environ["LONGPORT_REGION"] = region
            logger.debug("[Longbridge] 同步 LONGPORT_REGION=%s", region)

        urls = _REGION_URL_MAP.get(region, {})
        for env_name, default_url in (
            ("LONGBRIDGE_HTTP_URL", urls.get("http_url")),
            ("LONGBRIDGE_QUOTE_WS_URL", urls.get("quote_ws_url")),
            ("LONGBRIDGE_TRADE_WS_URL", urls.get("trade_ws_url")),
        ):
            if default_url and not os.environ.get(env_name):
                os.environ[env_name] = default_url
                logger.debug("[Longbridge] 根据 REGION=%s 设置 %s=%s", region, env_name, default_url)


@dataclass(frozen=True, slots=True)
class LongbridgeConfig:
    static_info_ttl_seconds: int = _DEFAULT_STATIC_INFO_TTL
    connection_cooldown_seconds: int = _DEFAULT_CONNECTION_COOLDOWN_SECONDS
    http_url: str | None = None
    quote_ws_url: str | None = None
    trade_ws_url: str | None = None
    region: str | None = None
    enable_overnight: bool = False
    push_candlestick_mode: str | None = None
    print_quote_packages: bool = False
    log_path: str | None = None


@lru_cache(maxsize=1)
def get_longbridge_config() -> LongbridgeConfig:
    sanitize_longbridge_env()

    region = (env_str("LONGBRIDGE_REGION") or "").strip().lower() or None
    region_urls = _REGION_URL_MAP.get(region or "", {})
    http_url = (env_str("LONGBRIDGE_HTTP_URL") or "").strip() or region_urls.get("http_url")
    quote_ws_url = (env_str("LONGBRIDGE_QUOTE_WS_URL") or "").strip() or region_urls.get("quote_ws_url")
    trade_ws_url = (env_str("LONGBRIDGE_TRADE_WS_URL") or "").strip() or region_urls.get("trade_ws_url")
    log_path = (env_str("LONGBRIDGE_LOG_PATH") or "").strip() or None

    return LongbridgeConfig(
        static_info_ttl_seconds=env_int("LONGBRIDGE_STATIC_INFO_TTL_SECONDS", _DEFAULT_STATIC_INFO_TTL, minimum=0),
        connection_cooldown_seconds=env_int(
            "LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS",
            _DEFAULT_CONNECTION_COOLDOWN_SECONDS,
            minimum=0,
        ),
        http_url=http_url or None,
        quote_ws_url=quote_ws_url or None,
        trade_ws_url=trade_ws_url or None,
        region=region,
        enable_overnight=env_bool("LONGBRIDGE_ENABLE_OVERNIGHT", False),
        push_candlestick_mode=(env_str("LONGBRIDGE_PUSH_CANDLESTICK_MODE") or "").strip().lower() or None,
        print_quote_packages=env_bool("LONGBRIDGE_PRINT_QUOTE_PACKAGES", False),
        log_path=log_path,
    )


def get_longbridge_sdk_kwargs() -> Dict[str, Any]:
    """Build optional kwargs for ``Config.from_apikey``."""
    try:
        from longbridge.openapi import Config, Language, PushCandlestickMode
    except Exception:
        return {}

    try:
        params = inspect.signature(Config.from_apikey).parameters
    except Exception:
        return {}

    config = get_longbridge_config()
    kwargs: Dict[str, Any] = {}

    if "enable_print_quote_packages" in params:
        kwargs["enable_print_quote_packages"] = config.print_quote_packages

    for param_name, value in (
        ("http_url", config.http_url),
        ("quote_ws_url", config.quote_ws_url),
        ("trade_ws_url", config.trade_ws_url),
    ):
        if param_name in params and value:
            kwargs[param_name] = value

    if "language" in params:
        try:
            from finance_analysis.reporting.localization import normalize_report_language

            report_language = normalize_report_language(os.getenv("REPORT_LANGUAGE"), default="zh")
            if report_language == "zh":
                kwargs["language"] = Language.ZH_CN
            elif report_language == "en":
                kwargs["language"] = Language.EN
        except Exception as exc:
            logger.debug("Longbridge language from REPORT_LANGUAGE skipped: %s", exc)

    if "enable_overnight" in params and env_str("LONGBRIDGE_ENABLE_OVERNIGHT", "").strip():
        kwargs["enable_overnight"] = config.enable_overnight

    if "push_candlestick_mode" in params and config.push_candlestick_mode:
        if config.push_candlestick_mode == "realtime":
            kwargs["push_candlestick_mode"] = PushCandlestickMode.Realtime
        elif config.push_candlestick_mode == "confirmed":
            kwargs["push_candlestick_mode"] = PushCandlestickMode.Confirmed
        else:
            logger.warning(
                "Unknown LONGBRIDGE_PUSH_CANDLESTICK_MODE=%r; use realtime or confirmed",
                config.push_candlestick_mode,
            )

    if "log_path" in params and config.log_path:
        kwargs["log_path"] = config.log_path

    return kwargs

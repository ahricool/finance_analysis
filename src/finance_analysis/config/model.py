# -*- coding: utf-8 -*-
"""
===================================
Finance Analysis - 配置管理模块
===================================

职责：
1. 使用单例模式管理全局配置
2. 从 .env 文件加载敏感配置
3. 提供类型安全的配置访问接口
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import unquote, urlparse
from dotenv import load_dotenv, dotenv_values
from dataclasses import MISSING, dataclass, field, fields

from finance_analysis.reporting.localization import (
    is_supported_report_language_value,
    normalize_report_language,
)
from finance_analysis.notification.routing import parse_notification_route_channels
from finance_analysis.notification.noise_control import (
    NOTIFICATION_SEVERITIES,
    is_supported_notification_severity,
    parse_notification_quiet_hours,
    validate_notification_timezone,
)

from .constants import AGENT_MAX_STEPS_DEFAULT
from .env_parsing import (
    parse_env_bool,
    parse_env_float,
    parse_env_int,
    parse_optional_env_int,
)
from .news import normalize_news_strategy_profile, resolve_news_window_days
from .llm import resolve_unified_llm_temperature
from .agent_models import (
    get_effective_agent_primary_model,
    normalize_agent_litellm_model,
)

logger = logging.getLogger(__name__)

# Project root (config package lives at ``<root>/src/config``); resolve the
# ``.env`` location relative to it so the package layout does not change which
# file is loaded.
from finance_analysis.core.paths import get_env_file_path


@dataclass
class ConfigIssue:
    """Structured configuration validation issue with a severity level.

    Attributes:
        severity: One of "error", "warning", or "info".
        message:  Human-readable description of the issue.
        field:    The environment variable / config field name most relevant to
                  this issue (empty string when not applicable).
    """

    severity: Literal["error", "warning", "info"]
    message: str
    field: str = ""

    def __str__(self) -> str:  # noqa: D105
        return self.message


def _has_ntfy_topic_endpoint(value: Optional[str]) -> bool:
    """Return whether an ntfy URL points at a concrete topic endpoint."""
    raw_url = (value or "").strip()
    if not raw_url:
        return False
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False
    return any(unquote(segment).strip() for segment in parsed.path.split("/") if segment)


def setup_env(override: bool = False):
    """
    Initialize environment variables from .env file.

    Args:
        override: If True, overwrite existing environment variables with values
                  from .env file. Set to True when reloading config after updates.
                  Default is False to preserve behavior on initial load where
                  system environment variables take precedence.
    """
    Config._capture_bootstrap_runtime_env_overrides()
    env_path = get_env_file_path()
    # Resolve ``load_dotenv`` through the package namespace so that tests which
    # patch ``src.config.load_dotenv`` keep working after the package split.
    _pkg = sys.modules.get(__package__)
    _load_dotenv = getattr(_pkg, "load_dotenv", load_dotenv) if _pkg else load_dotenv
    _load_dotenv(dotenv_path=env_path, override=override)

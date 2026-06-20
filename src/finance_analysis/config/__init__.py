# -*- coding: utf-8 -*-
"""Finance Analysis configuration package."""

from __future__ import annotations

import os  # noqa: F401
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from finance_analysis.config.constants import (
    AGENT_MAX_STEPS_DEFAULT,
    NEWS_STRATEGY_WINDOWS,
    SUPPORTED_LLM_CHANNEL_PROTOCOLS,
    _FALSEY_ENV_VALUES,
    _FIXED_TEMPERATURE_LITELLM_MODELS,
    _MANAGED_LITELLM_KEY_PROVIDERS,
)
from finance_analysis.config.env_parsing import (
    env_bool,
    env_float,
    env_int,
    env_list,
    env_str,
    parse_env_bool,
    parse_env_float,
    parse_env_int,
    parse_optional_env_int,
)
from finance_analysis.config.news import normalize_news_strategy_profile, resolve_news_window_days
from finance_analysis.config.llm import (
    canonicalize_llm_channel_protocol,
    channel_allows_empty_api_key,
    get_configured_llm_models,
    get_fixed_litellm_temperature,
    normalize_litellm_temperature,
    normalize_llm_channel_model,
    resolve_litellm_thinking_enabled,
    resolve_litellm_wire_model,
    resolve_llm_channel_protocol,
    resolve_unified_llm_temperature,
)
from finance_analysis.config.agent_models import (
    get_effective_agent_models_to_try,
    get_effective_agent_primary_model,
    normalize_agent_litellm_model,
)
from finance_analysis.config.model import (
    Config,
    ConfigIssue,
    get_config,
    load_dotenv,
    setup_env,
    _has_ntfy_topic_endpoint,
)

from finance_analysis.core.paths import repo_root

_PROJECT_ROOT = repo_root()


def _env_path() -> Path:
    configured = os.getenv("ENV_FILE")
    if configured:
        return Path(configured).expanduser()
    return _PROJECT_ROOT / ".env"


@lru_cache(maxsize=1)
def load_env() -> Path:
    """Load the active env file once and return its path."""
    env_path = _env_path()
    load_dotenv(dotenv_path=env_path, override=False)
    return env_path


__all__ = [
    "AGENT_MAX_STEPS_DEFAULT",
    "NEWS_STRATEGY_WINDOWS",
    "SUPPORTED_LLM_CHANNEL_PROTOCOLS",
    "Config",
    "ConfigIssue",
    "canonicalize_llm_channel_protocol",
    "channel_allows_empty_api_key",
    "env_bool",
    "env_float",
    "env_int",
    "env_list",
    "env_str",
    "get_config",
    "get_configured_llm_models",
    "get_effective_agent_models_to_try",
    "get_effective_agent_primary_model",
    "get_fixed_litellm_temperature",
    "load_dotenv",
    "load_env",
    "normalize_agent_litellm_model",
    "normalize_litellm_temperature",
    "normalize_llm_channel_model",
    "normalize_news_strategy_profile",
    "parse_env_bool",
    "parse_env_float",
    "parse_env_int",
    "parse_optional_env_int",
    "resolve_litellm_thinking_enabled",
    "resolve_litellm_wire_model",
    "resolve_llm_channel_protocol",
    "resolve_news_window_days",
    "resolve_unified_llm_temperature",
    "setup_env",
    "_FALSEY_ENV_VALUES",
    "_FIXED_TEMPERATURE_LITELLM_MODELS",
    "_MANAGED_LITELLM_KEY_PROVIDERS",
    "_has_ntfy_topic_endpoint",
]

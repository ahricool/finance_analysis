# -*- coding: utf-8 -*-
"""Finance Analysis configuration package.

This package was split out of the former monolithic ``src/config.py`` module.
All previously public names remain importable from ``src.config`` for backward
compatibility.
"""

# ``os`` is re-exported so that tests patching ``src.config.os.getenv`` (which
# historically targeted the monolithic module) keep affecting the global ``os``
# module used across the config package.
import os  # noqa: F401

from .constants import (
    AGENT_MAX_STEPS_DEFAULT,
    NEWS_STRATEGY_WINDOWS,
    SUPPORTED_LLM_CHANNEL_PROTOCOLS,
    _FALSEY_ENV_VALUES,
    _FIXED_TEMPERATURE_LITELLM_MODELS,
    _MANAGED_LITELLM_KEY_PROVIDERS,
)
from .env_parsing import (
    parse_env_bool,
    parse_env_float,
    parse_env_int,
    parse_optional_env_int,
)
from .news import (
    normalize_news_strategy_profile,
    resolve_news_window_days,
)
from .llm import (
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
    _get_litellm_provider,
    _uses_direct_env_provider,
)
from .agent_models import (
    get_effective_agent_models_to_try,
    get_effective_agent_primary_model,
    normalize_agent_litellm_model,
)
from .model import (
    Config,
    ConfigIssue,
    get_config,
    load_dotenv,
    setup_env,
    _has_ntfy_topic_endpoint,
)

__all__ = [
    # constants
    "AGENT_MAX_STEPS_DEFAULT",
    "NEWS_STRATEGY_WINDOWS",
    "SUPPORTED_LLM_CHANNEL_PROTOCOLS",
    # env parsing
    "parse_env_bool",
    "parse_env_float",
    "parse_env_int",
    "parse_optional_env_int",
    # news strategy
    "normalize_news_strategy_profile",
    "resolve_news_window_days",
    # llm helpers
    "canonicalize_llm_channel_protocol",
    "channel_allows_empty_api_key",
    "get_configured_llm_models",
    "get_fixed_litellm_temperature",
    "normalize_litellm_temperature",
    "normalize_llm_channel_model",
    "resolve_litellm_thinking_enabled",
    "resolve_litellm_wire_model",
    "resolve_llm_channel_protocol",
    "resolve_unified_llm_temperature",
    # agent models
    "get_effective_agent_models_to_try",
    "get_effective_agent_primary_model",
    "normalize_agent_litellm_model",
    # config model
    "Config",
    "ConfigIssue",
    "get_config",
    "setup_env",
    "load_dotenv",
    # backward-compatible re-exports of internal helpers
    "_FALSEY_ENV_VALUES",
    "_FIXED_TEMPERATURE_LITELLM_MODELS",
    "_MANAGED_LITELLM_KEY_PROVIDERS",
    "_get_litellm_provider",
    "_uses_direct_env_provider",
    "_has_ntfy_topic_endpoint",
]

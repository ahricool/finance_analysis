# -*- coding: utf-8 -*-
"""Finance Analysis configuration package."""

from __future__ import annotations

import os  # noqa: F401
from importlib import import_module
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from finance_analysis.config.env_parsing import (
    _FALSE_VALUES as _FALSEY_ENV_VALUES,
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

from finance_analysis.core.paths import get_env_file_path

_LAZY_EXPORTS = {
    "AGENT_MAX_STEPS_DEFAULT": ("finance_analysis.agent.config", "AGENT_MAX_STEPS_DEFAULT"),
    "NEWS_STRATEGY_WINDOWS": ("finance_analysis.search.config", "NEWS_STRATEGY_WINDOWS"),
    "SUPPORTED_LLM_CHANNEL_PROTOCOLS": ("finance_analysis.llm.config", "SUPPORTED_LLM_CHANNEL_PROTOCOLS"),
    "_FIXED_TEMPERATURE_LITELLM_MODELS": ("finance_analysis.llm.config", "_FIXED_TEMPERATURE_LITELLM_MODELS"),
    "_MANAGED_LITELLM_KEY_PROVIDERS": ("finance_analysis.llm.config", "_MANAGED_LITELLM_KEY_PROVIDERS"),
    "canonicalize_llm_channel_protocol": ("finance_analysis.llm.config", "canonicalize_llm_channel_protocol"),
    "channel_allows_empty_api_key": ("finance_analysis.llm.config", "channel_allows_empty_api_key"),
    "get_configured_llm_models": ("finance_analysis.llm.config", "get_configured_llm_models"),
    "get_effective_agent_models_to_try": ("finance_analysis.agent.config", "get_effective_agent_models_to_try"),
    "get_effective_agent_primary_model": ("finance_analysis.agent.config", "get_effective_agent_primary_model"),
    "get_fixed_litellm_temperature": ("finance_analysis.llm.config", "get_fixed_litellm_temperature"),
    "normalize_agent_litellm_model": ("finance_analysis.agent.config", "normalize_agent_litellm_model"),
    "normalize_litellm_temperature": ("finance_analysis.llm.config", "normalize_litellm_temperature"),
    "normalize_llm_channel_model": ("finance_analysis.llm.config", "normalize_llm_channel_model"),
    "normalize_news_strategy_profile": ("finance_analysis.search.config", "normalize_news_strategy_profile"),
    "resolve_litellm_thinking_enabled": ("finance_analysis.llm.config", "resolve_litellm_thinking_enabled"),
    "resolve_litellm_wire_model": ("finance_analysis.llm.config", "resolve_litellm_wire_model"),
    "resolve_llm_channel_protocol": ("finance_analysis.llm.config", "resolve_llm_channel_protocol"),
    "resolve_news_window_days": ("finance_analysis.search.config", "resolve_news_window_days"),
    "resolve_unified_llm_temperature": ("finance_analysis.llm.config", "resolve_unified_llm_temperature"),
    "_has_ntfy_topic_endpoint": ("finance_analysis.notification.config", "has_ntfy_topic_endpoint"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

@lru_cache(maxsize=1)
def load_env() -> Path:
    """Load the active env file once and return its path."""
    env_path = get_env_file_path()
    load_dotenv(dotenv_path=env_path, override=False)
    return env_path


def setup_env(override: bool = False) -> None:
    """Load the active env file, optionally overriding existing variables."""
    load_dotenv(dotenv_path=get_env_file_path(), override=override)


__all__ = [
    "AGENT_MAX_STEPS_DEFAULT",
    "NEWS_STRATEGY_WINDOWS",
    "SUPPORTED_LLM_CHANNEL_PROTOCOLS",
    "canonicalize_llm_channel_protocol",
    "channel_allows_empty_api_key",
    "env_bool",
    "env_float",
    "env_int",
    "env_list",
    "env_str",
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

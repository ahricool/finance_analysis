# -*- coding: utf-8 -*-
"""LLM-owned configuration and LiteLLM helper functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from finance_analysis.config.env_parsing import env_float, env_list, env_str

SUPPORTED_LLM_CHANNEL_PROTOCOLS = ("openai", "anthropic", "gemini", "vertex_ai", "deepseek", "ollama")
_MANAGED_LITELLM_KEY_PROVIDERS = {"gemini", "vertex_ai", "anthropic", "openai", "deepseek"}
_FIXED_TEMPERATURE_LITELLM_MODELS: Dict[str, Dict[str, float]] = {
    "kimi-k2.6": {"thinking": 1.0, "non_thinking": 0.6},
}


@dataclass
class LLMConfig:
    model: str = ""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.7
    fallback_models: List[str] = field(default_factory=list)
    request_delay: float = 2.0
    max_retries: int = 5
    retry_delay: float = 5.0

    @property
    def llm_model(self) -> str:
        return self.model

    @property
    def llm_base_url(self) -> Optional[str]:
        return self.base_url

    @property
    def llm_api_key(self) -> Optional[str]:
        return self.api_key

    @property
    def llm_temperature(self) -> float:
        return self.temperature

    @property
    def llm_fallback_models(self) -> List[str]:
        return self.fallback_models

    @property
    def llm_request_delay(self) -> float:
        return self.request_delay

    @property
    def llm_max_retries(self) -> int:
        return self.max_retries

    @property
    def llm_retry_delay(self) -> float:
        return self.retry_delay


@lru_cache(maxsize=1)
def get_llm_config() -> LLMConfig:
    return LLMConfig(
        model=(env_str("LLM_MODEL", "") or "").strip(),
        base_url=(env_str("LLM_BASE_URL", "") or "").strip() or None,
        api_key=(env_str("LLM_API_KEY", "") or "").strip() or None,
        temperature=env_float("LLM_TEMPERATURE", 0.7, minimum=0.0, maximum=2.0),
        fallback_models=env_list("LLM_FALLBACK_MODELS"),
    )


def canonicalize_llm_channel_protocol(value: Optional[str]) -> str:
    candidate = (value or "").strip().lower().replace("-", "_")
    aliases = {
        "openai_compatible": "openai",
        "openai_compat": "openai",
        "claude": "anthropic",
        "google": "gemini",
        "vertex": "vertex_ai",
        "vertexai": "vertex_ai",
    }
    return aliases.get(candidate, candidate)


def resolve_llm_channel_protocol(
    protocol: Optional[str],
    *,
    base_url: Optional[str] = None,
    models: Optional[List[str]] = None,
    channel_name: Optional[str] = None,
) -> str:
    explicit = canonicalize_llm_channel_protocol(protocol)
    if explicit in SUPPORTED_LLM_CHANNEL_PROTOCOLS:
        return explicit
    for model in models or []:
        if "/" in model:
            prefix = canonicalize_llm_channel_protocol(model.split("/", 1)[0])
            if prefix in SUPPORTED_LLM_CHANNEL_PROTOCOLS:
                return prefix
    if channel_name:
        named = canonicalize_llm_channel_protocol(channel_name)
        if named in SUPPORTED_LLM_CHANNEL_PROTOCOLS:
            return named
    if base_url:
        return "openai"
    return ""


def channel_allows_empty_api_key(protocol: Optional[str], base_url: Optional[str]) -> bool:
    if resolve_llm_channel_protocol(protocol, base_url=base_url) == "ollama":
        return True
    parsed = urlparse(base_url or "")
    return parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0"}


def normalize_llm_channel_model(model: str, protocol: Optional[str], base_url: Optional[str] = None) -> str:
    normalized_model = model.strip()
    if not normalized_model:
        return normalized_model
    resolved_protocol = resolve_llm_channel_protocol(protocol, base_url=base_url, models=[normalized_model])
    if "/" in normalized_model:
        raw_prefix, remainder = normalized_model.split("/", 1)
        canonical_prefix = canonicalize_llm_channel_protocol(raw_prefix.lower())
        known = _MANAGED_LITELLM_KEY_PROVIDERS | set(SUPPORTED_LLM_CHANNEL_PROTOCOLS) | {
            "minimax", "cohere", "huggingface", "bedrock", "sagemaker", "azure",
            "replicate", "together_ai", "palm", "text-completion-openai", "groq",
            "cerebras", "fireworks_ai", "friendliai",
        }
        if raw_prefix.lower() in known:
            return normalized_model
        if canonical_prefix in known:
            return f"{canonical_prefix}/{remainder}"
        if resolved_protocol:
            return f"{resolved_protocol}/{normalized_model}"
        return normalized_model
    return f"{resolved_protocol}/{normalized_model}" if resolved_protocol else normalized_model


def get_configured_llm_models(model_list: List[Dict[str, Any]]) -> List[str]:
    models: List[str] = []
    seen: set[str] = set()
    for entry in model_list or []:
        name = str(entry.get("model_name") or "").strip()
        if not name:
            params = entry.get("litellm_params", {}) or {}
            name = str(params.get("model") or "").strip()
        if not name or name.startswith("__legacy_") or name in seen:
            continue
        seen.add(name)
        models.append(name)
    return models


def _resolve_litellm_model_list_entry(model: str, model_list: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    normalized_model = (model or "").strip()
    if not normalized_model or not model_list:
        return None
    for entry in model_list:
        model_name = str(entry.get("model_name") or "").strip()
        if not model_name:
            params = entry.get("litellm_params", {}) or {}
            model_name = str(params.get("model") or "").strip()
        if model_name == normalized_model:
            return entry
    return None


def resolve_litellm_wire_model(model: str, model_list: Optional[List[Dict[str, Any]]] = None) -> str:
    entry = _resolve_litellm_model_list_entry((model or "").strip(), model_list)
    if not entry:
        return (model or "").strip()
    params = entry.get("litellm_params", {}) or {}
    return str(params.get("model") or "").strip() or (model or "").strip()


def _extract_thinking_config(payload: Optional[Dict[str, Any]]) -> Any:
    if not isinstance(payload, dict):
        return None
    extra_body = payload.get("extra_body")
    if isinstance(extra_body, dict) and "thinking" in extra_body:
        return extra_body.get("thinking")
    return payload.get("thinking")


def _parse_thinking_enabled(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"enabled", "enable", "true", "1", "on", "thinking"}:
            return True
        if normalized in {"disabled", "disable", "false", "0", "off", "none", "non-thinking", "non_thinking"}:
            return False
    if isinstance(value, dict):
        if "enabled" in value:
            return _parse_thinking_enabled(value.get("enabled"))
        if "type" in value:
            return _parse_thinking_enabled(value.get("type"))
    return None


def resolve_litellm_thinking_enabled(
    model: str,
    model_list: Optional[List[Dict[str, Any]]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
) -> Optional[bool]:
    thinking_config = None
    entry = _resolve_litellm_model_list_entry(model, model_list)
    if entry:
        thinking_config = _extract_thinking_config(entry)
        params = entry.get("litellm_params", {}) or {}
        param_config = _extract_thinking_config(params)
        if param_config is not None:
            thinking_config = param_config
    override = _extract_thinking_config(request_overrides)
    if override is not None:
        thinking_config = override
    return _parse_thinking_enabled(thinking_config)


def get_fixed_litellm_temperature(
    model: str,
    model_list: Optional[List[Dict[str, Any]]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    normalized_model = resolve_litellm_wire_model(model, model_list).lower()
    if not normalized_model:
        return None
    thinking_enabled = resolve_litellm_thinking_enabled(
        model,
        model_list=model_list,
        request_overrides=request_overrides,
    )
    model_parts = [part for part in re.split(r"[/:\s]+", normalized_model) if part]
    for model_name, temperatures in _FIXED_TEMPERATURE_LITELLM_MODELS.items():
        if any(part == model_name or part.startswith(f"{model_name}-") for part in model_parts):
            if thinking_enabled is False and temperatures.get("non_thinking") is not None:
                return temperatures["non_thinking"]
            return temperatures.get("thinking") or temperatures.get("non_thinking")
    return None


def normalize_litellm_temperature(
    model: str,
    temperature: Optional[float],
    *,
    default: float = 0.7,
    model_list: Optional[List[Dict[str, Any]]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
) -> float:
    fixed_temperature = get_fixed_litellm_temperature(
        model,
        model_list=model_list,
        request_overrides=request_overrides,
    )
    if fixed_temperature is not None:
        return fixed_temperature
    if temperature is None:
        return default
    return float(temperature)


def resolve_unified_llm_temperature(model: str) -> float:
    del model
    return env_float("LLM_TEMPERATURE", 0.7, minimum=0.0, maximum=2.0)


def _get_litellm_provider(model: str) -> str:
    if not model:
        return ""
    return model.split("/", 1)[0] if "/" in model else "openai"


def _uses_direct_env_provider(model: str) -> bool:
    provider = _get_litellm_provider(model)
    return bool(provider) and provider not in _MANAGED_LITELLM_KEY_PROVIDERS

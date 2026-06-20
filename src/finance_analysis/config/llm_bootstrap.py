# -*- coding: utf-8 -*-
"""Bootstrap multi-tier LLM configuration from environment variables.

Restores backward-compatible loading for tests and legacy deployments that
still rely on ``LITELLM_MODEL``, ``LLM_CHANNELS``, ``LITELLM_CONFIG``, and
per-provider API keys.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from finance_analysis.config.env_parsing import parse_env_bool
from finance_analysis.config.llm import (
    canonicalize_llm_channel_protocol,
    channel_allows_empty_api_key,
    get_configured_llm_models,
    normalize_llm_channel_model,
    resolve_llm_channel_protocol,
    resolve_unified_llm_temperature,
)
from finance_analysis.config.agent_models import normalize_agent_litellm_model
from finance_analysis.config.constants import SUPPORTED_LLM_CHANNEL_PROTOCOLS
from finance_analysis.core.paths import repo_root

logger = logging.getLogger(__name__)

ANSPIRE_LLM_BASE_URL_DEFAULT = "https://open-gateway.anspire.cn/v6"
ANSPIRE_LLM_MODEL_DEFAULT = "Doubao-Seed-2.0-lite"


@dataclass
class LLMBootstrapResult:
    llm_model: str = ""
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_fallback_models: List[str] = field(default_factory=list)
    litellm_config_path: Optional[str] = None
    llm_models_source: str = "legacy_env"
    llm_channels: List[Dict[str, Any]] = field(default_factory=list)
    llm_model_list: List[Dict[str, Any]] = field(default_factory=list)
    openai_base_url: Optional[str] = None
    gemini_api_keys: List[str] = field(default_factory=list)
    anthropic_api_keys: List[str] = field(default_factory=list)
    openai_api_keys: List[str] = field(default_factory=list)
    deepseek_api_keys: List[str] = field(default_factory=list)
    agent_litellm_model: str = ""


def parse_litellm_yaml(config_path: str) -> List[Dict[str, Any]]:
    """Parse a standard LiteLLM config YAML file into Router model_list."""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed; LITELLM_CONFIG ignored. Install with: pip install pyyaml")
        return []

    path = Path(config_path)
    if not path.is_absolute():
        path = repo_root() / path
    if not path.exists():
        logger.warning("LITELLM_CONFIG file not found: %s", path)
        return []

    try:
        with open(path, encoding="utf-8") as handle:
            yaml_config = yaml.safe_load(handle) or {}
    except Exception as exc:
        logger.warning("Failed to parse LITELLM_CONFIG: %s", exc)
        return []

    model_list = yaml_config.get("model_list", [])
    if not isinstance(model_list, list):
        logger.warning("LITELLM_CONFIG: model_list must be a list")
        return []

    for entry in model_list:
        params = entry.get("litellm_params", {})
        for key in list(params.keys()):
            value = params.get(key)
            if isinstance(value, str) and value.startswith("os.environ/"):
                env_name = value.split("/", 1)[1]
                params[key] = os.getenv(env_name, "")

    logger.info("LITELLM_CONFIG: loaded %s model deployment(s) from %s", len(model_list), path)
    return model_list


def parse_llm_channels(channels_str: str) -> List[Dict[str, Any]]:
    """Parse ``LLM_CHANNELS`` and per-channel environment variables."""
    channels: List[Dict[str, Any]] = []
    for raw_name in channels_str.split(","):
        ch_name = raw_name.strip()
        if not ch_name:
            continue
        ch_lower = ch_name.lower()
        ch_upper = ch_name.upper()

        base_url = os.getenv(f"LLM_{ch_upper}_BASE_URL", "").strip() or None
        if ch_lower == "anspire" and not base_url:
            base_url = (os.getenv("ANSPIRE_LLM_BASE_URL") or ANSPIRE_LLM_BASE_URL_DEFAULT).strip() or None
        protocol_raw = os.getenv(f"LLM_{ch_upper}_PROTOCOL", "").strip()
        if ch_lower == "anspire" and not protocol_raw:
            protocol_raw = "openai"
        enabled_raw = os.getenv(f"LLM_{ch_upper}_ENABLED")
        if ch_lower == "anspire" and (enabled_raw is None or not enabled_raw.strip()):
            enabled_raw = os.getenv("ANSPIRE_LLM_ENABLED")
        enabled = parse_env_bool(enabled_raw, default=True)

        api_keys_raw = os.getenv(f"LLM_{ch_upper}_API_KEYS", "")
        api_keys = [key.strip() for key in api_keys_raw.split(",") if key.strip()]
        if not api_keys:
            single_key = os.getenv(f"LLM_{ch_upper}_API_KEY", "").strip()
            if single_key:
                api_keys = [single_key]
        if not api_keys and ch_lower == "anspire":
            anspire_keys_raw = os.getenv("ANSPIRE_API_KEYS", "")
            api_keys = [key.strip() for key in anspire_keys_raw.split(",") if key.strip()]

        models_raw = os.getenv(f"LLM_{ch_upper}_MODELS", "")
        raw_models = [model.strip() for model in models_raw.split(",") if model.strip()]
        if not raw_models and ch_lower == "anspire":
            anspire_model = (os.getenv("ANSPIRE_LLM_MODEL") or ANSPIRE_LLM_MODEL_DEFAULT).strip()
            if anspire_model:
                raw_models = [anspire_model]
        protocol = resolve_llm_channel_protocol(
            protocol_raw,
            base_url=base_url,
            models=raw_models,
            channel_name=ch_name,
        )
        models = [normalize_llm_channel_model(model, protocol, base_url) for model in raw_models]

        extra_headers_raw = os.getenv(f"LLM_{ch_upper}_EXTRA_HEADERS", "").strip()
        extra_headers = None
        if extra_headers_raw:
            try:
                extra_headers = json.loads(extra_headers_raw)
            except json.JSONDecodeError:
                logger.warning("LLM_%s_EXTRA_HEADERS: invalid JSON, ignored", ch_upper)

        if not enabled:
            logger.info("LLM channel '%s': disabled, skipped", ch_name)
            continue

        if protocol_raw and canonicalize_llm_channel_protocol(protocol_raw) not in SUPPORTED_LLM_CHANNEL_PROTOCOLS:
            logger.warning(
                "LLM_%s_PROTOCOL=%s is unsupported; auto-detected protocol=%s",
                ch_upper,
                protocol_raw,
                protocol or "unknown",
            )

        if not api_keys and channel_allows_empty_api_key(protocol, base_url):
            api_keys = [""]

        if not api_keys:
            logger.warning("LLM channel '%s': no API key configured, skipped", ch_name)
            continue
        if not models:
            logger.warning("LLM channel '%s': no models configured, skipped", ch_name)
            continue

        channels.append(
            {
                "name": ch_name.lower(),
                "protocol": protocol,
                "enabled": enabled,
                "base_url": base_url,
                "api_keys": api_keys,
                "models": models,
                "extra_headers": extra_headers,
            }
        )
        logger.info("LLM channel '%s': %s model(s), %s key(s)", ch_name, len(models), len(api_keys))

    return channels


def channels_to_model_list(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert parsed LLM channels to LiteLLM Router model_list format."""
    model_list: List[Dict[str, Any]] = []
    for channel in channels:
        for model_name in channel["models"]:
            for api_key in channel["api_keys"]:
                litellm_params: Dict[str, Any] = {"model": model_name}
                if api_key:
                    litellm_params["api_key"] = api_key
                if channel["base_url"]:
                    litellm_params["api_base"] = channel["base_url"]
                headers = dict(channel.get("extra_headers") or {})
                if channel["base_url"] and "aihubmix.com" in channel["base_url"]:
                    headers.setdefault("APP-Code", "GPIJ3886")
                if headers:
                    litellm_params["extra_headers"] = headers
                model_list.append({"model_name": model_name, "litellm_params": litellm_params})
    return model_list


def legacy_keys_to_model_list(
    gemini_keys: List[str],
    anthropic_keys: List[str],
    openai_keys: List[str],
    openai_base_url: Optional[str],
    deepseek_keys: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Build Router model_list from legacy per-provider keys."""
    model_list: List[Dict[str, Any]] = []

    for key in gemini_keys:
        if key and len(key) >= 8:
            model_list.append(
                {"model_name": "__legacy_gemini__", "litellm_params": {"model": "__legacy_gemini__", "api_key": key}}
            )

    for key in anthropic_keys:
        if key and len(key) >= 8:
            model_list.append(
                {
                    "model_name": "__legacy_anthropic__",
                    "litellm_params": {"model": "__legacy_anthropic__", "api_key": key},
                }
            )

    for key in openai_keys:
        if key and len(key) >= 8:
            params: Dict[str, Any] = {"model": "__legacy_openai__", "api_key": key}
            if openai_base_url:
                params["api_base"] = openai_base_url
            if openai_base_url and "aihubmix.com" in openai_base_url:
                params["extra_headers"] = {"APP-Code": "GPIJ3886"}
            model_list.append({"model_name": "__legacy_openai__", "litellm_params": params})

    for key in deepseek_keys or []:
        if key and len(key) >= 8:
            model_list.append(
                {"model_name": "__legacy_deepseek__", "litellm_params": {"model": "__legacy_deepseek__", "api_key": key}}
            )

    return model_list


def bootstrap_llm_config_from_env() -> LLMBootstrapResult:
    """Load unified + legacy LLM configuration from the current environment."""
    gemini_keys_raw = os.getenv("GEMINI_API_KEYS", "")
    gemini_api_keys = [key.strip() for key in gemini_keys_raw.split(",") if key.strip()]
    single_gemini = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_api_keys and single_gemini:
        gemini_api_keys = [single_gemini]

    anthropic_keys_raw = os.getenv("ANTHROPIC_API_KEYS", "")
    anthropic_api_keys = [key.strip() for key in anthropic_keys_raw.split(",") if key.strip()]
    single_anthropic = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not anthropic_api_keys and single_anthropic:
        anthropic_api_keys = [single_anthropic]

    aihubmix = os.getenv("AIHUBMIX_KEY", "").strip()
    openai_keys_raw = os.getenv("OPENAI_API_KEYS", "")
    openai_api_keys = [key.strip() for key in openai_keys_raw.split(",") if key.strip()]
    if not openai_api_keys:
        single_openai = os.getenv("OPENAI_API_KEY", "").strip()
        fallback_key = aihubmix or single_openai
        if fallback_key:
            openai_api_keys = [fallback_key]
    openai_base_url = os.getenv("OPENAI_BASE_URL") or ("https://aihubmix.com/v1" if aihubmix else None)

    deepseek_keys_raw = os.getenv("DEEPSEEK_API_KEYS", "")
    deepseek_api_keys = [key.strip() for key in deepseek_keys_raw.split(",") if key.strip()]
    if not deepseek_api_keys:
        single_deepseek = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if single_deepseek:
            deepseek_api_keys = [single_deepseek]

    anspire_keys_raw = os.getenv("ANSPIRE_API_KEYS", "")
    anspire_api_keys = [key.strip() for key in anspire_keys_raw.split(",") if key.strip()]
    anspire_llm_enabled = parse_env_bool(os.getenv("ANSPIRE_LLM_ENABLED"), default=True)
    anspire_llm_base_url = (os.getenv("ANSPIRE_LLM_BASE_URL") or ANSPIRE_LLM_BASE_URL_DEFAULT).strip()
    anspire_llm_model_env = os.getenv("ANSPIRE_LLM_MODEL", "").strip()
    anspire_channel_disabled = False
    for raw_channel in os.getenv("LLM_CHANNELS", "").split(","):
        if raw_channel.strip().lower() != "anspire":
            continue
        channel_enabled_raw = os.getenv("LLM_ANSPIRE_ENABLED")
        if channel_enabled_raw is not None and channel_enabled_raw.strip():
            anspire_channel_disabled = not parse_env_bool(channel_enabled_raw, default=True)
        else:
            anspire_channel_disabled = not anspire_llm_enabled
        break
    using_anspire_llm_legacy = bool(
        anspire_llm_enabled and not anspire_channel_disabled and anspire_api_keys and not openai_api_keys
    )
    if using_anspire_llm_legacy:
        openai_api_keys = list(anspire_api_keys)
        openai_base_url = anspire_llm_base_url

    llm_model = (os.getenv("LLM_MODEL") or os.getenv("LITELLM_MODEL") or "").strip()
    inferred_legacy_deepseek_model = False
    openai_model_env = os.getenv("OPENAI_MODEL", "").strip()
    if using_anspire_llm_legacy:
        openai_model_name = anspire_llm_model_env or openai_model_env or ANSPIRE_LLM_MODEL_DEFAULT
    else:
        openai_model_name = openai_model_env or "gpt-5.5"
    if not llm_model:
        gemini_model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview").strip()
        anthropic_model_name = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
        if gemini_api_keys:
            llm_model = f"gemini/{gemini_model_name}"
        elif anthropic_api_keys:
            llm_model = f"anthropic/{anthropic_model_name}"
        elif deepseek_api_keys:
            llm_model = "deepseek/deepseek-chat"
            inferred_legacy_deepseek_model = True
        elif openai_api_keys:
            llm_model = f"openai/{openai_model_name}" if "/" not in openai_model_name else openai_model_name

    fallback_str = (os.getenv("LLM_FALLBACK_MODELS") or os.getenv("LITELLM_FALLBACK_MODELS") or "").strip()
    if fallback_str:
        llm_fallback_models = [model.strip() for model in fallback_str.split(",") if model.strip()]
    else:
        gemini_fallback = os.getenv("GEMINI_MODEL_FALLBACK", "gemini-3-flash-preview").strip()
        if llm_model.startswith("gemini/") and gemini_fallback:
            fallback_model = f"gemini/{gemini_fallback}" if "/" not in gemini_fallback else gemini_fallback
            llm_fallback_models = [fallback_model]
        else:
            llm_fallback_models = []

    litellm_config_path = os.getenv("LITELLM_CONFIG", "").strip() or None
    llm_models_source = "legacy_env"
    llm_channels: List[Dict[str, Any]] = []
    llm_model_list: List[Dict[str, Any]] = []

    if litellm_config_path:
        from finance_analysis.config.model import Config

        llm_model_list = Config._parse_litellm_yaml(litellm_config_path)
        if llm_model_list:
            llm_models_source = "litellm_config"

    if not llm_model_list:
        channels_str = os.getenv("LLM_CHANNELS", "").strip()
        if channels_str:
            llm_channels = parse_llm_channels(channels_str)
            llm_model_list = channels_to_model_list(llm_channels)
            if llm_model_list:
                llm_models_source = "llm_channels"

    if not llm_model_list:
        llm_model_list = legacy_keys_to_model_list(
            gemini_api_keys,
            anthropic_api_keys,
            openai_api_keys,
            openai_base_url,
            deepseek_api_keys,
        )
        if llm_model_list:
            llm_models_source = "legacy_env"

    if (
        inferred_legacy_deepseek_model
        and llm_models_source == "legacy_env"
        and llm_model == "deepseek/deepseek-chat"
    ):
        logger.warning(
            "Deprecation warning:\n"
            "deepseek-chat will be deprecated on 2026-07-24,\n"
            "please migrate to deepseek-v4-flash."
        )

    if not llm_model and llm_channels:
        for channel in llm_channels:
            if channel.get("models"):
                llm_model = channel["models"][0]
                break

    if not llm_fallback_models and llm_channels and llm_model:
        all_channel_models: List[str] = []
        for channel in llm_channels:
            all_channel_models.extend(channel.get("models", []))
        seen = {llm_model}
        llm_fallback_models = [model for model in all_channel_models if model not in seen and not seen.add(model)]  # type: ignore[func-returns-value]

    agent_litellm_model = normalize_agent_litellm_model(os.getenv("AGENT_LITELLM_MODEL", ""))
    configured_models = set(get_configured_llm_models(llm_model_list))
    if configured_models and agent_litellm_model and agent_litellm_model not in configured_models:
        agent_litellm_model = normalize_agent_litellm_model(agent_litellm_model)

    llm_api_key = (os.getenv("LLM_API_KEY", "") or "").strip() or None
    llm_base_url = (os.getenv("LLM_BASE_URL", "") or "").strip() or openai_base_url

    return LLMBootstrapResult(
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_fallback_models=llm_fallback_models,
        litellm_config_path=litellm_config_path,
        llm_models_source=llm_models_source,
        llm_channels=llm_channels,
        llm_model_list=llm_model_list,
        openai_base_url=openai_base_url,
        gemini_api_keys=gemini_api_keys,
        anthropic_api_keys=anthropic_api_keys,
        openai_api_keys=openai_api_keys,
        deepseek_api_keys=deepseek_api_keys,
        agent_litellm_model=agent_litellm_model,
    )


__all__ = [
    "LLMBootstrapResult",
    "bootstrap_llm_config_from_env",
    "channels_to_model_list",
    "legacy_keys_to_model_list",
    "parse_litellm_yaml",
    "parse_llm_channels",
]

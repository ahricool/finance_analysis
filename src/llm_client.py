# -*- coding: utf-8 -*-
"""Unified LiteLLM completion helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.config import Config, normalize_litellm_temperature

logger = logging.getLogger(__name__)


class LLMConfigError(ValueError):
    """Raised when required LLM configuration is missing or invalid."""


def _model_requires_api_key(model: str, base_url: Optional[str]) -> bool:
    """Return whether a model is expected to require an API key."""
    normalized_model = (model or "").strip().lower()
    if normalized_model.startswith("ollama/"):
        return False
    if base_url:
        lowered = base_url.lower()
        if "localhost" in lowered or "127.0.0.1" in lowered:
            return False
    return True


def validate_llm_config(config: Config, *, model: Optional[str] = None) -> None:
    """Validate that the requested model can be called with the current config."""
    resolved_model = (model or getattr(config, "llm_model", "") or "").strip()
    if not resolved_model:
        raise LLMConfigError("LLM_MODEL is not configured")

    api_key = (getattr(config, "llm_api_key", "") or "").strip()
    base_url = (getattr(config, "llm_base_url", "") or "").strip() or None
    if _model_requires_api_key(resolved_model, base_url) and not api_key:
        raise LLMConfigError("LLM_API_KEY is not configured")


def get_models_to_try(config: Config) -> List[str]:
    """Return primary model followed by configured fallback models."""
    models = [getattr(config, "llm_model", "")] + list(getattr(config, "llm_fallback_models", []) or [])
    ordered: List[str] = []
    seen = set()
    for model in models:
        normalized = (model or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def build_completion_kwargs(
    config: Config,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build kwargs for litellm.completion without mutating caller input."""
    validate_llm_config(config, model=model)

    effective_temperature = (
        config.llm_temperature if temperature is None else temperature
    )
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": normalize_litellm_temperature(
            model,
            effective_temperature,
            model_list=None,
            request_overrides=extra.get("request_overrides"),
        ),
    }
    api_key = (getattr(config, "llm_api_key", "") or "").strip()
    if api_key:
        kwargs["api_key"] = api_key

    base_url = (getattr(config, "llm_base_url", "") or "").strip()
    if base_url:
        # LiteLLM expects api_base; do not append /chat/completions here.
        kwargs["api_base"] = base_url.rstrip("/")

    for key, value in extra.items():
        if key == "request_overrides":
            continue
        kwargs[key] = value
    return kwargs


def completion(
    config: Config,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    **extra: Any,
) -> Any:
    """Call litellm.completion for one model."""
    import litellm

    call_kwargs = build_completion_kwargs(
        config,
        model,
        messages,
        temperature=temperature,
        **extra,
    )
    return litellm.completion(**call_kwargs)


def completion_with_fallback(
    config: Config,
    messages: List[Dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    **extra: Any,
) -> Tuple[Any, str]:
    """Try primary model, then fallback models in order."""
    models = get_models_to_try(config)
    if not models:
        raise LLMConfigError("LLM_MODEL is not configured")

    last_error: Optional[Exception] = None
    for model in models:
        try:
            response = completion(
                config,
                model,
                messages,
                temperature=temperature,
                **extra,
            )
            return response, model
        except LLMConfigError:
            raise
        except Exception as exc:
            logger.warning("LLM call failed for %s: %s", model, exc)
            last_error = exc

    if last_error is not None:
        raise last_error
    raise LLMConfigError("All configured LLM models failed")


def is_llm_configured(config: Config) -> bool:
    """Return whether the runtime has enough config to attempt an LLM call."""
    try:
        validate_llm_config(config)
        return bool(get_models_to_try(config))
    except LLMConfigError:
        return False

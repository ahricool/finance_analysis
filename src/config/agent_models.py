# -*- coding: utf-8 -*-
"""Agent model resolution helpers (primary model + fallback inheritance)."""

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .model import Config


def normalize_agent_litellm_model(model: str) -> str:
    """Normalize AGENT_LITELLM_MODEL into a LiteLLM model id."""
    normalized_model = (model or "").strip()
    if not normalized_model:
        return ""
    if "/" not in normalized_model:
        return f"openai/{normalized_model}"
    return normalized_model


def get_effective_agent_primary_model(config: "Config") -> str:
    """Return the effective Agent primary model with fallback inheritance."""
    configured_agent_model = normalize_agent_litellm_model(
        getattr(config, "agent_litellm_model", ""),
    )
    if configured_agent_model:
        return configured_agent_model
    return (getattr(config, "llm_model", "") or "").strip()


def get_effective_agent_models_to_try(config: "Config") -> List[str]:
    """Return Agent model try-order: primary + global fallbacks (deduped)."""
    raw_models = [get_effective_agent_primary_model(config)] + (
        getattr(config, "llm_fallback_models", []) or []
    )
    seen = set()
    ordered_models: List[str] = []
    for model in raw_models:
        normalized_model = (model or "").strip()
        if not normalized_model or normalized_model in seen:
            continue
        seen.add(normalized_model)
        ordered_models.append(normalized_model)
    return ordered_models

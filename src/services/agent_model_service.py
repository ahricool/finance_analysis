# -*- coding: utf-8 -*-
"""Helpers for exposing configured Agent model deployments."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agent.config import get_effective_agent_models_to_try, get_effective_agent_primary_model


def _get_model_provider(model_name: str) -> str:
    if not model_name:
        return "unknown"
    if "/" in model_name:
        return model_name.split("/", 1)[0]
    return "openai"


def list_agent_model_deployments(config) -> List[Dict[str, Any]]:
    """Return configured Agent model deployments derived from unified LLM config."""
    ordered_models = get_effective_agent_models_to_try(config)
    if not ordered_models:
        return []

    primary_model = get_effective_agent_primary_model(config)
    fallback_set = set(ordered_models[1:])
    base_url = getattr(config, "llm_base_url", None)

    deployments: List[Dict[str, Any]] = []
    for index, model_name in enumerate(ordered_models):
        deployments.append(
            {
                "deployment_id": f"llm:{index}:{model_name}",
                "model": model_name,
                "provider": _get_model_provider(model_name),
                "source": "llm_env",
                "api_base": str(base_url).strip() if base_url else None,
                "deployment_name": model_name,
                "is_primary": model_name == primary_model,
                "is_fallback": model_name in fallback_set,
            }
        )
    return deployments

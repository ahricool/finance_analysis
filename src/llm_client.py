# -*- coding: utf-8 -*-
"""Compatibility exports for the unified LiteLLM client package."""

from src.llm.client import (
    AllModelsFailedError,
    LLMClient,
    LLMConfigError,
    _model_requires_api_key,
    build_completion_kwargs,
    completion,
    completion_with_fallback,
    get_models_to_try,
    is_llm_configured,
    validate_llm_config,
)
from src.llm.types import LLMRequest, LLMResult

__all__ = [
    "AllModelsFailedError",
    "LLMClient",
    "LLMConfigError",
    "LLMRequest",
    "LLMResult",
    "_model_requires_api_key",
    "build_completion_kwargs",
    "completion",
    "completion_with_fallback",
    "get_models_to_try",
    "is_llm_configured",
    "validate_llm_config",
]

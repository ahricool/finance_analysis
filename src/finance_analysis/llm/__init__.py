# -*- coding: utf-8 -*-
"""Unified LLM client package."""

from finance_analysis.llm.client import (
    AllModelsFailedError,
    LLMClient,
    LLMConfigError,
    completion,
    completion_with_fallback,
    is_llm_configured,
)
from finance_analysis.llm.types import LLMRequest, LLMResult

__all__ = [
    "AllModelsFailedError",
    "LLMClient",
    "LLMConfigError",
    "LLMRequest",
    "LLMResult",
    "completion",
    "completion_with_fallback",
    "is_llm_configured",
]

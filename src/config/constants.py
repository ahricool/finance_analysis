# -*- coding: utf-8 -*-
"""Shared constants for the configuration package."""

from typing import Dict

# Providers whose API keys are managed/injected via LiteLLM env handling.
_MANAGED_LITELLM_KEY_PROVIDERS = {"gemini", "vertex_ai", "anthropic", "openai", "deepseek"}

# Channel protocols understood by the LLM resolution helpers.
SUPPORTED_LLM_CHANNEL_PROTOCOLS = ("openai", "anthropic", "gemini", "vertex_ai", "deepseek", "ollama")

# Environment-style values treated as falsey by ``parse_env_bool``.
_FALSEY_ENV_VALUES = {"0", "false", "no", "off"}

# Kimi K2.6 is consumed through Moonshot's OpenAI-compatible API in this
# repository. Official references:
# - https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart
# - https://platform.moonshot.ai/docs/guide/compatibility#parameters-differences-in-request-body
# - https://huggingface.co/moonshotai/Kimi-K2.6
# - https://docs.litellm.ai/docs/providers/openai_compatible
# Only the strict Kimi K2.6 family is normalized here; other models and
# fallbacks continue using the configured runtime temperature.
_FIXED_TEMPERATURE_LITELLM_MODELS: Dict[str, Dict[str, float]] = {
    "kimi-k2.6": {
        "thinking": 1.0,
        "non_thinking": 0.6,
    },
}

AGENT_MAX_STEPS_DEFAULT = 10

NEWS_STRATEGY_WINDOWS: Dict[str, int] = {
    "ultra_short": 1,
    "short": 3,
    "medium": 7,
    "long": 30,
}

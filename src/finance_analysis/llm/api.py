"""The only LiteLLM transport call. Retries belong to LLMClient."""

import re
from typing import Any

from .config import LLMConfig
from .types import LLMRequest, LLMResult


def _get(value: Any, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def complete(config: LLMConfig, request: LLMRequest) -> LLMResult:
    import litellm

    messages = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    messages.append({"role": "user", "content": request.prompt})
    temperature = config.temperature if request.temperature is None else request.temperature
    # Kimi K2.6 defaults to thinking mode and requires temperature=1.
    if re.search(r"(?:^|[/ :])kimi-k2\.6(?:$|-)", config.model.lower()):
        temperature = 1.0
    kwargs = dict(
        model=config.model,
        api_key=config.api_key,
        messages=messages,
        temperature=temperature,
        timeout=request.timeout or config.timeout,
        num_retries=0,
    )
    if config.base_url:
        kwargs["api_base"] = config.base_url.rstrip("/")
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    if request.web_search:
        # LiteLLM/OpenAI-compatible web search. Prompt still restricts the
        # search to the current symbol; this is review, not signal generation.
        kwargs["web_search_options"] = {"search_context_size": "medium"}
    response = litellm.completion(**kwargs)
    choices = _get(response, "choices", [])
    content = _get(_get(choices[0], "message"), "content") if choices else None
    if isinstance(content, list):
        content = "".join(_get(part, "text", "") for part in content)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM returned empty response")
    raw_usage = _get(response, "usage")
    usage = {
        "input_tokens": int(_get(raw_usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(_get(raw_usage, "completion_tokens", 0) or 0),
        "total_tokens": int(_get(raw_usage, "total_tokens", 0) or 0),
    }
    return LLMResult(text=content, backend="api", model=config.model, usage=usage)

"""The only LiteLLM transport call. Retries belong to LLMClient."""

import time
from typing import Any

from .config import LLMConfig
from .failures import ProviderFailure
from .search import evidence, supported
from .types import LLMRequest, LLMResult


def _get(value: Any, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def complete(config: LLMConfig, request: LLMRequest) -> LLMResult:
    import litellm

    if request.web_search and supported(config) and config.api_search_mode == "responses":
        return _complete_responses(config, request)
    messages = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    messages.append({"role": "user", "content": request.prompt})
    kwargs = dict(
        model=config.model,
        api_key=config.api_key,
        messages=messages,
        timeout=request.timeout or config.attempt_timeout,
        num_retries=0,
    )
    if config.base_url:
        kwargs["api_base"] = config.base_url.rstrip("/")
    if config.api_effort:
        kwargs["reasoning_effort"] = config.api_effort
        if config.model.startswith("openai/"):
            # Allow new OpenAI models before LiteLLM's model catalog catches up.
            kwargs["allowed_openai_params"] = ["reasoning_effort"]
    if request.web_search and supported(config):
        # LiteLLM/OpenAI-compatible web search. Prompt still restricts the
        # search to the current symbol; this is review, not signal generation.
        kwargs["web_search_options"] = {"search_context_size": "medium"}
    started = time.monotonic()
    try:
        response = litellm.completion(**kwargs)
    finally:
        request.diagnostics["api_ms"] = round((time.monotonic() - started) * 1000)
    choices = _get(response, "choices", [])
    content = _get(_get(choices[0], "message"), "content") if choices else None
    if isinstance(content, list):
        content = "".join(_get(part, "text", "") for part in content)
    if not isinstance(content, str) or not content.strip():
        raise ProviderFailure("empty_response", retryable=True)
    raw_usage = _get(response, "usage")
    usage = {
        "input_tokens": int(_get(raw_usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(_get(raw_usage, "completion_tokens", 0) or 0),
        "total_tokens": int(_get(raw_usage, "total_tokens", 0) or 0),
    }
    annotations = _get(_get(choices[0], "message"), "annotations", []) or []
    citations = []
    for annotation in annotations:
        if _get(annotation, "type") == "url_citation":
            c = _get(annotation, "url_citation", annotation)
            url = _get(c, "url", "")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                citations.append(dict(url=url, title=_get(c, "title", "")))
    return LLMResult(
        text=content,
        backend="api",
        model=config.model,
        usage=usage,
        search_evidence=evidence(request.web_search, supported(config), citations),
    )


def _complete_responses(config: LLMConfig, request: LLMRequest) -> LLMResult:
    import litellm

    kwargs = dict(
        model=config.model,
        api_key=config.api_key,
        input=request.prompt,
        tools=[{"type": "web_search", "search_context_size": "medium"}],
        timeout=request.timeout or config.attempt_timeout,
        num_retries=0,
        store=False,
    )
    if config.base_url:
        kwargs["api_base"] = config.base_url.rstrip("/")
    if request.system_prompt:
        kwargs["instructions"] = request.system_prompt
    if config.api_effort:
        kwargs["reasoning"] = {"effort": config.api_effort}
    started = time.monotonic()
    try:
        response = litellm.responses(**kwargs)
    finally:
        request.diagnostics["api_ms"] = round((time.monotonic() - started) * 1000)
    # A partial answer or a started search is not successful research.
    if _get(response, "status") != "completed":
        raise ProviderFailure("invalid_output", retryable=True)
    texts, citations, events = [], [], []
    for item in _get(response, "output", []) or []:
        kind = _get(item, "type")
        if kind == "web_search_call" and _get(item, "status") == "completed":
            action = _get(item, "action")
            if hasattr(action, "model_dump"):
                action = action.model_dump(mode="json")
            events.append(dict(id=_get(item, "id"), type=kind, status="completed", action=action))
        if kind != "message":
            continue
        for part in _get(item, "content", []) or []:
            if _get(part, "type") != "output_text":
                continue
            texts.append(_get(part, "text", ""))
            for annotation in _get(part, "annotations", []) or []:
                url = _get(annotation, "url", "")
                if _get(annotation, "type") == "url_citation" and isinstance(url, str) and url.startswith(
                    ("https://", "http://")
                ):
                    citations.append(dict(url=url, title=_get(annotation, "title", "")))
    content = "\n".join(texts)
    if not content.strip():
        raise ProviderFailure("empty_response", retryable=True)
    raw_usage = _get(response, "usage")
    return LLMResult(
        text=content,
        backend="api",
        model=config.model,
        usage={key: int(_get(raw_usage, key, 0) or 0) for key in ("input_tokens", "output_tokens", "total_tokens")},
        search_evidence=evidence(request.web_search, supported(config), citations, events),
    )

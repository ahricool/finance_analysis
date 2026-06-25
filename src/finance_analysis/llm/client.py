# -*- coding: utf-8 -*-
"""Unified LiteLLM client and completion helpers."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from finance_analysis.llm.config import LLMConfig, get_llm_config, normalize_litellm_temperature
from finance_analysis.llm.types import LLMRequest, LLMResult

logger = logging.getLogger(__name__)

_LLM_WEB_PROVIDER = "llm_web"
_LLM_WEB_MODEL_DEFAULT = "gemini-3.5-flash"
_LLM_WEB_BASE_URL_DEFAULT = "http://host.docker.internal:8001/v1"
_LLM_WEB_EMPTY_API_KEY_PLACEHOLDER = "not-needed"

_AUTO_THINKING_MODELS: List[str] = ["deepseek-reasoner", "deepseek-r1", "qwq"]
_OPT_IN_THINKING_MODELS: Dict[str, dict] = {
    "deepseek-chat": {"thinking": {"type": "enabled"}},
}


def _model_matches(model: str, entries: List[str]) -> bool:
    if not model:
        return False
    normalized = model.lower().strip()
    for entry in entries:
        if normalized == entry or normalized.startswith(entry + "-"):
            return True
    return False


def get_thinking_extra_body(model: str) -> Optional[dict]:
    if _model_matches(model, _AUTO_THINKING_MODELS):
        return None
    normalized = (model or "").lower().strip()
    for key, payload in _OPT_IN_THINKING_MODELS.items():
        if normalized == key or normalized.startswith(key + "-"):
            return payload
    return None


class LLMConfigError(ValueError):
    """Raised when required LLM configuration is missing or invalid."""


class _LiteLLMStreamError(RuntimeError):
    """Internal error wrapper that records whether any text was streamed."""

    def __init__(self, message: str, *, partial_received: bool = False):
        super().__init__(message)
        self.partial_received = partial_received


class AllModelsFailedError(Exception):
    """Raised when every model in the fallback chain fails."""

    def __init__(
        self,
        message: str,
        *,
        last_response_text: Optional[str] = None,
        last_model: Optional[str] = None,
        last_usage: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.last_response_text = last_response_text
        self.last_model = last_model
        self.last_usage = last_usage or {}


def _model_requires_api_key(model: str, base_url: Optional[str]) -> bool:
    normalized_model = (model or "").strip().lower()
    if normalized_model.startswith("ollama/"):
        return False
    if base_url:
        lowered = base_url.lower()
        if "localhost" in lowered or "127.0.0.1" in lowered:
            return False
    return True


def validate_llm_config(
    config: LLMConfig,
    *,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    allow_empty_api_key: bool = False,
) -> None:
    resolved_model = (model or getattr(config, "llm_model", "") or "").strip()
    if not resolved_model:
        raise LLMConfigError("LLM_MODEL is not configured")

    resolved_api_key = (api_key if api_key is not None else getattr(config, "llm_api_key", "") or "").strip()
    base_url = (api_base if api_base is not None else getattr(config, "llm_base_url", "") or "").strip() or None
    if not allow_empty_api_key and _model_requires_api_key(resolved_model, base_url) and not resolved_api_key:
        raise LLMConfigError("LLM_API_KEY is not configured")


def get_models_to_try(config: LLMConfig) -> List[str]:
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
    config: LLMConfig,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    allow_empty_api_key: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """Build kwargs for the single LiteLLM completion entry point."""
    validate_llm_config(
        config,
        model=model,
        api_base=api_base,
        api_key=api_key,
        allow_empty_api_key=allow_empty_api_key,
    )

    request_overrides = extra.pop("request_overrides", None)
    effective_temperature = config.llm_temperature if temperature is None else temperature
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": normalize_litellm_temperature(
            model,
            effective_temperature,
            model_list=None,
            request_overrides=request_overrides,
        ),
    }
    resolved_api_key = (api_key if api_key is not None else getattr(config, "llm_api_key", "") or "").strip()
    if resolved_api_key:
        kwargs["api_key"] = resolved_api_key
    elif allow_empty_api_key and api_key is not None:
        kwargs["api_key"] = _LLM_WEB_EMPTY_API_KEY_PLACEHOLDER

    base_url = (api_base if api_base is not None else getattr(config, "llm_base_url", "") or "").strip()
    if base_url:
        kwargs["api_base"] = base_url.rstrip("/")

    for key, value in extra.items():
        if value is not None:
            kwargs[key] = value
    return kwargs


def completion(
    config: LLMConfig,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    **extra: Any,
) -> Any:
    import litellm

    call_kwargs = build_completion_kwargs(config, model, messages, temperature=temperature, **extra)
    return litellm.completion(**call_kwargs)


def completion_with_fallback(
    config: LLMConfig,
    messages: List[Dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    **extra: Any,
) -> Tuple[Any, str]:
    models = get_models_to_try(config)
    if not models:
        raise LLMConfigError("LLM_MODEL is not configured")

    last_error: Optional[Exception] = None
    for model in models:
        try:
            response = completion(config, model, messages, temperature=temperature, **extra)
            return response, model
        except LLMConfigError:
            raise
        except Exception as exc:
            logger.warning("LLM call failed for %s: %s", model, exc)
            last_error = exc

    if last_error is not None:
        raise last_error
    raise LLMConfigError("All configured LLM models failed")


def is_llm_configured(config: LLMConfig) -> bool:
    try:
        validate_llm_config(config)
        return bool(get_models_to_try(config))
    except LLMConfigError:
        return False


class LLMClient:
    """Single application entry point for LiteLLM completions."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        models_to_try: Optional[Iterable[str]] = None,
    ):
        self.config = config or get_llm_config()
        self._models_to_try_override = [m for m in (models_to_try or []) if m]

    def is_available(self) -> bool:
        if self._models_to_try_override:
            try:
                for model in self._models_to_try_override:
                    validate_llm_config(self.config, model=model)
                return True
            except LLMConfigError:
                return False
        return is_llm_configured(self.config)

    def complete_text(self, request: LLMRequest) -> LLMResult:
        return self._complete(request)

    def complete_json(
        self,
        request: LLMRequest,
        validator: Callable[[str], None] | None = None,
    ) -> LLMResult:
        return self._complete(request, response_validator=validator)

    def complete_stream(
        self,
        request: LLMRequest,
        progress_callback: Callable[[int], None] | None = None,
    ) -> LLMResult:
        request.stream = True
        return self._complete(request, stream_progress_callback=progress_callback)

    def complete_with_tools(self, request: LLMRequest) -> LLMResult:
        return self._complete(request)

    def _models_to_try(self) -> List[str]:
        if self._models_to_try_override:
            return self._models_to_try_override
        return get_models_to_try(self.config)

    def _resolve_request_config(
        self,
        request: LLMRequest,
    ) -> tuple[list[str], Optional[str], Optional[str]]:
        provider = (request.provider or "").strip().lower()
        if not provider:
            return self._models_to_try(), None, None

        if provider != _LLM_WEB_PROVIDER:
            raise LLMConfigError(f"Unsupported LLM provider: {request.provider}")

        web_model = (os.getenv("LLM_WEB_MODEL") or _LLM_WEB_MODEL_DEFAULT).strip()
        if not web_model:
            raise LLMConfigError("LLM_WEB_MODEL is not configured")
        if "/" not in web_model:
            web_model = f"openai/{web_model}"

        api_base = (os.getenv("LLM_WEB_BASE_URL") or _LLM_WEB_BASE_URL_DEFAULT).strip()
        if not api_base:
            raise LLMConfigError("LLM_WEB_BASE_URL is not configured")

        default_model = (getattr(self.config, "llm_model", "") or "").strip()
        if not default_model:
            raise LLMConfigError("LLM_MODEL is not configured for llm_web fallback")

        models_to_try: list[str] = []
        for model in (web_model, default_model):
            if model and model not in models_to_try:
                models_to_try.append(model)

        return models_to_try, api_base, (os.getenv("LLM_WEB_API_KEY") or "").strip()

    def _normalize_usage(self, usage_obj: Any) -> Dict[str, Any]:
        if not usage_obj:
            return {}

        def _get_value(key: str) -> int:
            if isinstance(usage_obj, dict):
                return int(usage_obj.get(key) or 0)
            return int(getattr(usage_obj, key, 0) or 0)

        return {
            "prompt_tokens": _get_value("prompt_tokens"),
            "completion_tokens": _get_value("completion_tokens"),
            "total_tokens": _get_value("total_tokens"),
        }

    def _extract_text(self, response: Any) -> Optional[str]:
        choices = getattr(response, "choices", None)
        if not choices and isinstance(response, dict):
            choices = response.get("choices")
        if not choices:
            return None
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        return content if isinstance(content, str) else None

    def _extract_stream_text(self, chunk: Any) -> str:
        choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
        if not choices:
            return ""

        choice = choices[0]
        delta = choice.get("delta") if isinstance(choice, dict) else getattr(choice, "delta", None)
        message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)

        content: Any = None
        if isinstance(delta, dict):
            content = delta.get("content")
        elif isinstance(delta, str):
            content = delta
        elif delta is not None:
            content = getattr(delta, "content", None)

        if content is None:
            if isinstance(message, dict):
                content = message.get("content")
            elif message is not None:
                content = getattr(message, "content", None)

        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)

        return content if isinstance(content, str) else ""

    def _consume_stream(
        self,
        stream_response: Any,
        *,
        model: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        chunks: List[str] = []
        usage: Dict[str, Any] = {}
        chars_received = 0
        next_emit_at = 1

        try:
            for chunk in stream_response:
                chunk_usage = chunk.get("usage") if isinstance(chunk, dict) else getattr(chunk, "usage", None)
                normalized_usage = self._normalize_usage(chunk_usage)
                if normalized_usage:
                    usage = normalized_usage

                delta_text = self._extract_stream_text(chunk)
                if not delta_text:
                    continue

                chunks.append(delta_text)
                chars_received += len(delta_text)
                if progress_callback and chars_received >= next_emit_at:
                    progress_callback(chars_received)
                    next_emit_at = chars_received + 160
        except Exception as exc:
            raise _LiteLLMStreamError(
                f"{model} stream interrupted: {exc}",
                partial_received=chars_received > 0,
            ) from exc

        response_text = "".join(chunks).strip()
        if not response_text:
            raise _LiteLLMStreamError(
                f"{model} stream returned empty response",
                partial_received=False,
            )

        if progress_callback and chars_received > 0:
            progress_callback(chars_received)

        return response_text, usage

    def _build_kwargs_for_model(
        self,
        model: str,
        request: LLMRequest,
        *,
        stream: bool = False,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        model_short = model.split("/")[-1] if "/" in model else model
        thinking_extra = get_thinking_extra_body(model_short)
        extra_body = request.extra_body if request.extra_body is not None else thinking_extra
        request_overrides = {"extra_body": extra_body} if extra_body else None
        kwargs = build_completion_kwargs(
            self.config,
            model,
            request.messages,
            temperature=request.temperature,
            api_base=api_base,
            api_key=api_key,
            allow_empty_api_key=(request.provider or "").strip().lower() == _LLM_WEB_PROVIDER,
            max_tokens=request.max_tokens,
            stream=True if stream else None,
            tools=request.tools,
            timeout=request.timeout,
            extra_body=extra_body,
            request_overrides=request_overrides,
        )
        return kwargs

    def _dispatch_completion(self, kwargs: Dict[str, Any]) -> Any:
        import litellm

        return litellm.completion(**kwargs)

    def _complete(
        self,
        request: LLMRequest,
        *,
        stream_progress_callback: Optional[Callable[[int], None]] = None,
        response_validator: Optional[Callable[[str], None]] = None,
    ) -> LLMResult:
        models_to_try, api_base, api_key = self._resolve_request_config(request)
        if not models_to_try:
            raise LLMConfigError("LLM_MODEL is not configured")

        request_delay = float(getattr(self.config, "llm_request_delay", 0) or 0)
        if request_delay > 0 and request.call_type in {"analysis", "market_review"}:
            logger.debug("[LLM] waiting %.1f seconds before request", request_delay)
            time.sleep(request_delay)

        last_error = None
        last_response_text: Optional[str] = None
        last_model: Optional[str] = None
        last_usage: Dict[str, Any] = {}

        max_retries = int(getattr(self.config, "llm_max_retries", 0) or 0)
        retry_delay = float(getattr(self.config, "llm_retry_delay", 0) or 0)

        for model in models_to_try:
            attempts = max(1, max_retries + 1)
            for attempt in range(attempts):
                try:
                    if request.stream:
                        try:
                            stream_kwargs = self._build_kwargs_for_model(
                                model,
                                request,
                                stream=True,
                                api_base=api_base,
                                api_key=api_key,
                            )
                            stream_response = self._dispatch_completion(stream_kwargs)
                            text, usage = self._consume_stream(
                                stream_response,
                                model=model,
                                progress_callback=stream_progress_callback,
                            )
                            last_response_text = text
                            last_model = model
                            last_usage = usage
                            if response_validator is not None:
                                response_validator(text)
                            return LLMResult(text=text, model_used=model, usage=usage, raw=stream_response)
                        except _LiteLLMStreamError as exc:
                            logger.warning("[LiteLLM] %s stream failed, falling back to non-stream: %s", model, exc)
                            last_error = exc
                        except Exception as exc:
                            logger.warning("[LiteLLM] %s stream request failed, falling back to non-stream: %s", model, exc)
                            last_error = exc

                    call_kwargs = self._build_kwargs_for_model(
                        model,
                        request,
                        stream=False,
                        api_base=api_base,
                        api_key=api_key,
                    )
                    response = self._dispatch_completion(call_kwargs)
                    content = self._extract_text(response)
                    if content:
                        usage = self._normalize_usage(getattr(response, "usage", None))
                        last_response_text = content
                        last_model = model
                        last_usage = usage
                        if response_validator is not None:
                            response_validator(content)
                        return LLMResult(text=content, model_used=model, usage=usage, raw=response)
                    raise ValueError("LLM returned empty response")
                except Exception as exc:
                    logger.warning("[LiteLLM] %s failed on attempt %d/%d: %s", model, attempt + 1, attempts, exc)
                    last_error = exc
                    if attempt + 1 < attempts and retry_delay > 0:
                        time.sleep(retry_delay)
                    continue

        raise AllModelsFailedError(
            f"All LLM models failed (tried {len(models_to_try)} model(s)). Last error: {last_error}",
            last_response_text=last_response_text,
            last_model=last_model,
            last_usage=last_usage,
        )

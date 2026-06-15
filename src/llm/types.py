# -*- coding: utf-8 -*-
"""Shared request/response types for LiteLLM calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMRequest:
    messages: list[dict[str, Any]]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False
    tools: Optional[list[dict[str, Any]]] = None
    timeout: Optional[float] = None
    extra_body: Optional[dict[str, Any]] = None
    call_type: str = "generic"
    stock_code: Optional[str] = None


@dataclass
class LLMResult:
    text: Optional[str]
    model_used: Optional[str]
    usage: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

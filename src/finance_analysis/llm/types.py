"""Business-facing text requests and normalized backend results."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMRequest:
    prompt: str
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    call_type: str = "generic"
    uid: int | None = None
    web_search: bool = False


@dataclass
class LLMResult:
    text: str
    backend: str
    engine: str | None = None
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

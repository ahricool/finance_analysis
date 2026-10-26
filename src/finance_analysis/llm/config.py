"""Fixed Codex to API fallback, with per-attempt limits and bounded retries."""

import math
import os
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from finance_analysis.core.paths import get_log_dir


@dataclass
class LLMConfig:
    backend: str = "api"
    max_retries: int = 3
    attempt_timeout: float = 300
    codex_model: str = ""
    codex_effort: str = ""
    cli_codex_path: str = "/usr/local/bin/codex"
    cli_python_path: str = "/usr/bin/python3"
    log_dir: Path = field(default_factory=lambda: get_log_dir() / "llm")
    api_search_mode: str = "unavailable"
    model: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = field(default="", repr=False)
    temperature: float = 0.7
    cli_engine: str = "codex"
    cli_ssh_host: str = "host.docker.internal"
    cli_ssh_port: int = 22
    cli_ssh_username: str = ""
    cli_ssh_password: str = field(default="", repr=False)
    cli_remote_workdir: str = "/tmp/finance-analysis-llm"
    cli_model: str = ""
    cli_effort: str = ""

    def __post_init__(self):
        if self.api_search_mode not in {"unavailable", "chat_completions"}:
            raise ValueError("LLM_API_SEARCH_MODE must be unavailable or chat_completions")
        if self.backend not in {"api", "cli"}:
            raise ValueError("LLM_BACKEND must be api or cli")
        if self.cli_engine != "codex":
            raise ValueError("Only Codex CLI is supported")
        if self.max_retries not in {0, 1, 2, 3}:
            raise ValueError("LLM_MAX_RETRIES must be between 0 and 3")
        if not 1 <= self.cli_ssh_port <= 65535:
            raise ValueError("LLM_CLI_SSH_PORT must be between 1 and 65535")
        if not self.cli_remote_workdir.startswith("/") or self.cli_remote_workdir == "/":
            raise ValueError("LLM_CLI_REMOTE_WORKDIR must be an absolute dedicated directory")
        if self.cli_effort and self.cli_effort not in {
            "low",
            "medium",
            "high",
            "xhigh",
        }:
            raise ValueError("Invalid LLM_CLI_EFFORT")

        if not math.isfinite(self.attempt_timeout) or self.attempt_timeout <= 0:
            raise ValueError("LLM_ATTEMPT_TIMEOUT must be positive and finite")
        for value in (self.cli_codex_path, self.cli_python_path):
            if not value.startswith("/") or "\x00" in value:
                raise ValueError("CLI executable paths must be absolute")
        if self.codex_effort not in {"", "low", "medium", "high", "xhigh"}:
            raise ValueError("Invalid Codex effort")

    def providers(self) -> list["LLMConfig"]:
        return [
            replace(self, backend="cli", cli_engine="codex", cli_model=self.codex_model, cli_effort=self.codex_effort),
            replace(self, backend="api", cli_effort=""),
        ]

    def is_available(self) -> bool:
        return any(provider.is_configured() for provider in self.providers())

    def is_configured(self) -> bool:
        if self.backend == "cli":
            return bool(self.cli_ssh_host and self.cli_ssh_username and self.cli_ssh_password)
        return bool(self.model and self.api_key)


@lru_cache(maxsize=1)
def get_llm_config() -> LLMConfig:
    defaults = LLMConfig()
    values = {}
    for name in defaults.__dataclass_fields__:
        raw = os.getenv(f"LLM_{name.upper()}")
        if name in {"backend", "cli_engine", "cli_model", "cli_effort"} or raw is None:
            continue
        if name in {"max_retries", "cli_ssh_port"}:
            values[name] = int(raw)
        elif name in {"attempt_timeout", "temperature"}:
            values[name] = float(raw)
        elif name == "log_dir":
            values[name] = Path(raw).expanduser() if raw else defaults.log_dir
        else:
            values[name] = raw if name == "cli_ssh_password" else raw.strip()
    return LLMConfig(**values)

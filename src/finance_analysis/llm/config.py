"""Explicit ordered fallback, with isolated model settings and bounded retries."""

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
    timeout: float = 180
    fallback_chain: str = ""
    attempt_timeout: float = 180
    agy_model: str = ""
    agy_effort: str = ""
    codex_model: str = ""
    codex_effort: str = ""
    cli_agy_path: str = "/usr/local/bin/agy"
    cli_codex_path: str = "/usr/local/bin/codex"
    cli_python_path: str = "/usr/bin/python3"
    log_dir: Path = field(default_factory=lambda: get_log_dir() / "llm")
    model: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = field(default="", repr=False)
    temperature: float = 0.7
    cli_engine: str = "agy"
    cli_ssh_host: str = "host.docker.internal"
    cli_ssh_port: int = 22
    cli_ssh_username: str = ""
    cli_ssh_password: str = field(default="", repr=False)
    cli_remote_workdir: str = "/tmp/finance-analysis-llm"
    cli_model: str = ""
    cli_effort: str = ""

    def __post_init__(self):
        if self.backend not in {"api", "cli"}:
            raise ValueError("LLM_BACKEND must be api or cli")
        if self.cli_engine not in {"agy", "codex"}:
            raise ValueError("LLM_CLI_ENGINE must be agy or codex")
        if self.max_retries not in {0, 1, 2, 3}:
            raise ValueError("LLM_MAX_RETRIES must be between 0 and 3")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("LLM_TIMEOUT must be positive")
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
        if self.cli_engine == "agy" and self.cli_effort == "xhigh":
            raise ValueError("AGY effort must be low, medium or high")

        if not math.isfinite(self.attempt_timeout) or self.attempt_timeout <= 0:
            raise ValueError("LLM_ATTEMPT_TIMEOUT must be positive and finite")
        if self.fallback_chain and self.fallback_chain != "agy,codex,api":
            raise ValueError("LLM_FALLBACK_CHAIN must be empty or agy,codex,api")
        for value in (self.cli_agy_path, self.cli_codex_path, self.cli_python_path):
            if not value.startswith("/") or "\x00" in value:
                raise ValueError("CLI executable paths must be absolute")
        if self.agy_effort not in {"", "low", "medium", "high"}:
            raise ValueError("Invalid AGY effort")
        if self.codex_effort not in {"", "low", "medium", "high", "xhigh"}:
            raise ValueError("Invalid Codex effort")

    def providers(self) -> list["LLMConfig"]:
        if not self.fallback_chain:
            return [self]
        return [
            replace(
                self,
                fallback_chain="",
                backend="cli",
                cli_engine=engine,
                cli_model=getattr(self, f"{engine}_model"),
                cli_effort=getattr(self, f"{engine}_effort"),
            )
            for engine in ("agy", "codex")
        ] + [replace(self, fallback_chain="", backend="api", cli_effort="")]

    def is_available(self) -> bool:
        if self.fallback_chain:
            return any(config.is_available() for config in self.providers())
        if self.backend == "cli":
            return bool(self.cli_ssh_host and self.cli_ssh_username and self.cli_ssh_password)
        return bool(self.model and self.api_key)


@lru_cache(maxsize=1)
def get_llm_config() -> LLMConfig:
    defaults = LLMConfig()
    values = {}
    for name in defaults.__dataclass_fields__:
        raw = os.getenv(f"LLM_{name.upper()}")
        if raw is None:
            continue
        if name in {"max_retries", "cli_ssh_port"}:
            values[name] = int(raw)
        elif name in {"timeout", "attempt_timeout", "temperature"}:
            values[name] = float(raw)
        elif name == "log_dir":
            values[name] = Path(raw).expanduser() if raw else defaults.log_dir
        else:
            values[name] = raw if name == "cli_ssh_password" else raw.strip()
    return LLMConfig(**values)

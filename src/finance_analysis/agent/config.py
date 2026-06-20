# -*- coding: utf-8 -*-
"""Agent-owned configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import logging
from typing import List, Optional

from finance_analysis.llm.config import get_llm_config
from finance_analysis.config.env_parsing import env_str

logger = logging.getLogger(__name__)

AGENT_MAX_STEPS_DEFAULT = 10
_VALID_AGENT_ARCH = {"single", "multi"}
_VALID_ORCHESTRATOR_MODES = {"quick", "standard", "full", "specialist"}
_VALID_SKILL_ROUTING = {"auto", "manual"}


def normalize_agent_litellm_model(model: str) -> str:
    normalized_model = (model or "").strip()
    if not normalized_model:
        return ""
    if "/" not in normalized_model:
        return f"openai/{normalized_model}"
    return normalized_model


@dataclass
class AgentConfig:
    agent_litellm_model: str = ""
    agent_mode: bool = False
    agent_mode_explicit: bool = False
    agent_max_steps: int = AGENT_MAX_STEPS_DEFAULT
    agent_skills: List[str] = field(default_factory=list)
    agent_skill_dir: Optional[str] = None
    agent_nl_routing: bool = False
    agent_arch: str = "single"
    agent_orchestrator_mode: str = "standard"
    agent_orchestrator_timeout_s: int = 600
    agent_risk_override: bool = True
    agent_deep_research_budget: int = 30000
    agent_deep_research_timeout: int = 180
    agent_memory_enabled: bool = False
    agent_skill_autoweight: bool = True
    agent_skill_routing: str = "auto"
    agent_event_monitor_enabled: bool = False
    agent_event_alert_rules_json: str = ""

    def is_agent_available(self) -> bool:
        if self.agent_mode_explicit:
            return self.agent_mode
        return bool(get_effective_agent_primary_model(self))


def _normalize_agent_config(config: AgentConfig) -> AgentConfig:
    values = config.__dict__.copy()
    if config.agent_arch not in _VALID_AGENT_ARCH:
        logger.warning("Invalid AGENT_ARCH=%r; falling back to 'single'", config.agent_arch)
        values["agent_arch"] = "single"
    if config.agent_orchestrator_mode in {"strategy", "skill"}:
        logger.info("AGENT_ORCHESTRATOR_MODE=%s is deprecated; normalizing to 'specialist'", config.agent_orchestrator_mode)
        values["agent_orchestrator_mode"] = "specialist"
    if values["agent_orchestrator_mode"] not in _VALID_ORCHESTRATOR_MODES:
        logger.warning("Invalid AGENT_ORCHESTRATOR_MODE=%r; falling back to 'standard'", config.agent_orchestrator_mode)
        values["agent_orchestrator_mode"] = "standard"
    if config.agent_skill_routing not in _VALID_SKILL_ROUTING:
        logger.warning("Invalid AGENT_SKILL_ROUTING=%r; falling back to 'auto'", config.agent_skill_routing)
        values["agent_skill_routing"] = "auto"
    return AgentConfig(**values)


@lru_cache(maxsize=1)
def get_agent_config() -> AgentConfig:
    return _normalize_agent_config(
        AgentConfig(
            agent_litellm_model=normalize_agent_litellm_model(env_str("AGENT_LITELLM_MODEL", "") or ""),
        )
    )


def get_effective_agent_primary_model(config: object | None = None) -> str:
    agent_config = config or get_agent_config()
    configured_agent_model = normalize_agent_litellm_model(getattr(agent_config, "agent_litellm_model", ""))
    if configured_agent_model:
        return configured_agent_model
    return (getattr(agent_config, "llm_model", "") or get_llm_config().model or "").strip()


def get_effective_agent_models_to_try(config: object | None = None) -> List[str]:
    llm_config = get_llm_config()
    raw_models = [get_effective_agent_primary_model(config)] + list(
        getattr(config, "llm_fallback_models", llm_config.fallback_models) or []
    )
    seen: set[str] = set()
    ordered_models: List[str] = []
    for model in raw_models:
        normalized_model = (model or "").strip()
        if not normalized_model or normalized_model in seen:
            continue
        seen.add(normalized_model)
        ordered_models.append(normalized_model)
    return ordered_models

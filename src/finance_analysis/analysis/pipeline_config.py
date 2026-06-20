# -*- coding: utf-8 -*-
"""Configuration view used by the analysis pipeline.

The owning modules still define the actual settings. This view exists because
the pipeline coordinates LLM, Agent, search, data providers, reporting, and
notification in one workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from functools import lru_cache
from typing import Any

from finance_analysis.integrations.market_data.config import get_data_provider_config
from finance_analysis.agent.config import get_agent_config, get_effective_agent_primary_model
from finance_analysis.llm.config import get_llm_config
from finance_analysis.notification.config import get_notification_config
from finance_analysis.reporting.config import get_report_config
from finance_analysis.config.runtime import get_runtime_config
from finance_analysis.search.config import get_search_config


@dataclass(frozen=True)
class PipelineConfig:
    pass

    def is_agent_available(self) -> bool:
        return get_agent_config().is_agent_available()

    def has_searxng_enabled(self) -> bool:
        return get_search_config().has_searxng_enabled()

    def has_search_capability_enabled(self) -> bool:
        return get_search_config().has_search_capability_enabled()


def _asdict(obj: object) -> dict[str, Any]:
    return {field.name: getattr(obj, field.name) for field in fields(obj)}


@lru_cache(maxsize=1)
def get_pipeline_config() -> PipelineConfig:
    values: dict[str, Any] = {}
    llm_config = get_llm_config()
    for config in (
        llm_config,
        get_agent_config(),
        get_search_config(),
        get_data_provider_config(),
        get_notification_config(),
        get_report_config(),
        get_runtime_config(),
    ):
        values.update(_asdict(config))
    values.update(
        {
            "llm_model": llm_config.model,
            "litellm_model": llm_config.model,
            "llm_base_url": llm_config.base_url,
            "llm_api_key": llm_config.api_key,
            "llm_temperature": llm_config.temperature,
            "llm_fallback_models": llm_config.fallback_models,
            "llm_request_delay": llm_config.request_delay,
            "llm_max_retries": llm_config.max_retries,
            "llm_retry_delay": llm_config.retry_delay,
        }
    )

    cls = dataclass(frozen=True)(type("PipelineRuntimeConfig", (PipelineConfig,), {"__annotations__": {key: type(value) for key, value in values.items()}}))
    return cls(**values)

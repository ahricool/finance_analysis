# -*- coding: utf-8 -*-
"""Configuration view used by the analysis pipeline.

The owning modules still define the actual settings. This view exists because
the pipeline coordinates LLM, data providers, reporting, and
notification in one workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from functools import lru_cache
from typing import Any

from finance_analysis.integrations.market_data.config import get_data_provider_config
from finance_analysis.llm.config import get_llm_config
from finance_analysis.notification.config import get_notification_config
from finance_analysis.reporting.config import get_report_config
from finance_analysis.market_review.config import get_market_review_config
from finance_analysis.tasks.config import get_task_config


@dataclass
class PipelineConfig:
    pass


def _asdict(obj: object) -> dict[str, Any]:
    return {field.name: getattr(obj, field.name) for field in fields(obj)}


@lru_cache(maxsize=1)
def get_pipeline_config() -> PipelineConfig:
    values: dict[str, Any] = {}
    llm_config = get_llm_config()
    for config in (
        get_data_provider_config(),
        get_market_review_config(),
        get_notification_config(),
        get_report_config(),
        get_task_config(),
    ):
        values.update(_asdict(config))
    values["llm"] = llm_config

    cls = dataclass(type("PipelineRuntimeConfig", (PipelineConfig,), {"__annotations__": {key: type(value) for key, value in values.items()}}))
    return cls(**values)

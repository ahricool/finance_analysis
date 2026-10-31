"""Shared LLM/report language configuration for independent news and review jobs."""

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.llm.config import LLMConfig, get_llm_config
from finance_analysis.reporting.config import get_report_config


@dataclass(frozen=True)
class ReportRuntimeConfig:
    llm: LLMConfig
    report_language: str


@lru_cache(maxsize=1)
def get_report_runtime_config() -> ReportRuntimeConfig:
    return ReportRuntimeConfig(llm=get_llm_config(), report_language=get_report_config().report_language)

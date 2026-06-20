# -*- coding: utf-8 -*-
"""Report rendering and analysis-output configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import logging

from finance_analysis.reporting.localization import is_supported_report_language_value, normalize_report_language

logger = logging.getLogger(__name__)


def _parse_report_type(value: str | None) -> str:
    candidate = (value or "simple").strip().lower()
    if candidate in {"simple", "full", "brief"}:
        return candidate
    logger.warning("REPORT_TYPE %r invalid; falling back to 'simple'", value)
    return "simple"


def _parse_report_language(value: str | None) -> str:
    normalized = normalize_report_language(value, default="zh")
    raw = (value or "").strip()
    if raw and not is_supported_report_language_value(raw):
        logger.warning("REPORT_LANGUAGE %r invalid; falling back to 'zh'", value)
    return normalized


def _parse_md2img_engine(value: str | None) -> str:
    candidate = (value or "wkhtmltoimage").strip().lower()
    if candidate in {"wkhtmltoimage", "markdown-to-file"}:
        return candidate
    logger.warning("MD2IMG_ENGINE %r invalid; falling back to 'wkhtmltoimage'", value)
    return "wkhtmltoimage"


@dataclass
class ReportConfig:
    bias_threshold: float = 5.0
    single_stock_notify: bool = False
    report_type: str = "simple"
    report_language: str = "zh"
    report_summary_only: bool = False
    report_templates_dir: str = "templates"
    report_renderer_enabled: bool = False
    report_integrity_enabled: bool = True
    report_integrity_retry: int = 1
    report_history_compare_n: int = 0
    analysis_delay: float = 0.0
    markdown_to_image_channels: list[str] | None = field(default_factory=list)
    markdown_to_image_max_chars: int = 15000
    md2img_engine: str = "wkhtmltoimage"
    save_context_snapshot: bool = True

    def __post_init__(self) -> None:
        if self.markdown_to_image_channels is None:
            self.markdown_to_image_channels = []


@lru_cache(maxsize=1)
def get_report_config() -> ReportConfig:
    return ReportConfig()

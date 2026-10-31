# -*- coding: utf-8 -*-
"""Report rendering and analysis-output configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import logging

from finance_analysis.reporting.localization import is_supported_report_language_value, normalize_report_language

logger = logging.getLogger(__name__)


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
    report_language: str = "zh"
    markdown_to_image_channels: list[str] | None = field(default_factory=list)
    markdown_to_image_max_chars: int = 15000
    md2img_engine: str = "wkhtmltoimage"

    def __post_init__(self) -> None:
        if self.markdown_to_image_channels is None:
            self.markdown_to_image_channels = []


@lru_cache(maxsize=1)
def get_report_config() -> ReportConfig:
    return ReportConfig()

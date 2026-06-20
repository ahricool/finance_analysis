# -*- coding: utf-8 -*-
"""Report rendering and analysis-output configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging

from finance_analysis.reporting.localization import is_supported_report_language_value, normalize_report_language
from finance_analysis.config.env_parsing import env_bool, env_float, env_int, env_list, env_str

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


@dataclass(frozen=True)
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
    merge_email_notification: bool = False
    markdown_to_image_channels: list[str] | None = None
    markdown_to_image_max_chars: int = 15000
    md2img_engine: str = "wkhtmltoimage"
    save_context_snapshot: bool = True

    def __post_init__(self) -> None:
        if self.markdown_to_image_channels is None:
            object.__setattr__(self, "markdown_to_image_channels", [])


@lru_cache(maxsize=1)
def get_report_config() -> ReportConfig:
    return ReportConfig(
        bias_threshold=env_float("BIAS_THRESHOLD", 5.0, minimum=1.0),
        single_stock_notify=env_bool("SINGLE_STOCK_NOTIFY", False),
        report_type=_parse_report_type(env_str("REPORT_TYPE", "simple")),
        report_language=_parse_report_language(env_str("REPORT_LANGUAGE", "zh")),
        report_summary_only=env_bool("REPORT_SUMMARY_ONLY", False),
        report_templates_dir=env_str("REPORT_TEMPLATES_DIR", "templates") or "templates",
        report_renderer_enabled=env_bool("REPORT_RENDERER_ENABLED", False),
        report_integrity_enabled=env_bool("REPORT_INTEGRITY_ENABLED", True),
        report_integrity_retry=env_int("REPORT_INTEGRITY_RETRY", 1, minimum=0),
        report_history_compare_n=env_int("REPORT_HISTORY_COMPARE_N", 0, minimum=0),
        analysis_delay=env_float("ANALYSIS_DELAY", 0.0, minimum=0.0),
        merge_email_notification=env_bool("MERGE_EMAIL_NOTIFICATION", False),
        markdown_to_image_channels=[channel.lower() for channel in env_list("MARKDOWN_TO_IMAGE_CHANNELS")],
        markdown_to_image_max_chars=env_int("MARKDOWN_TO_IMAGE_MAX_CHARS", 15000, minimum=1),
        md2img_engine=_parse_md2img_engine(env_str("MD2IMG_ENGINE", "wkhtmltoimage")),
        save_context_snapshot=env_bool("SAVE_CONTEXT_SNAPSHOT", True),
    )

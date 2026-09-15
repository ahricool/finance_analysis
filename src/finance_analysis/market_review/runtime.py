"""Reusable market review runtime assembly helpers.

Centralize the analyzer/notification construction so API, CLI and Bot
entrypoints share one initialization path for 大盘复盘.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple


logger = logging.getLogger(__name__)


def has_configured_llm_runtime(config: object) -> bool:
    """Return whether unified LLM configuration is available."""
    return config.llm.is_available()


def build_market_review_runtime(
    config: object,
    source_message: Optional[Any] = None,
) -> Tuple[Any, Any]:
    """
    Build shared NotificationService, StockReportAnalyzer instances.
    """
    from finance_analysis.analysis.stock_report_analyzer import StockReportAnalyzer
    from finance_analysis.notification.service import NotificationService

    notifier = NotificationService(source_message=source_message)

    analyzer = None
    if has_configured_llm_runtime(config):
        analyzer = StockReportAnalyzer(config=config)
        if not analyzer.is_available():
            logger.warning("LLM analyzer initialized but not available (check LLM_MODEL / LLM_API_KEY)")

    return notifier, analyzer

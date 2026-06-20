"""Reusable market review runtime assembly helpers.

Centralize the analyzer/search/notification construction so API, CLI and Bot
entrypoints share one initialization path for 大盘复盘.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

from finance_analysis.llm.client import is_llm_configured

logger = logging.getLogger(__name__)


def has_configured_llm_runtime(config: object) -> bool:
    """Return whether unified LLM configuration is available."""
    return is_llm_configured(config)


def build_market_review_runtime(
    config: object,
    source_message: Optional[Any] = None,
) -> Tuple[Any, Any, Any]:
    """
    Build shared NotificationService, StockReportAnalyzer and SearchService instances.
    """
    from finance_analysis.analysis.stock_report_analyzer import StockReportAnalyzer
    from finance_analysis.notification.service import NotificationService
    from finance_analysis.search import SearchService

    notifier = NotificationService(source_message=source_message)

    search_service = None
    has_search_capability = getattr(config, "has_search_capability_enabled", None)
    if callable(has_search_capability) and has_search_capability():
        search_service = SearchService(
            bocha_keys=getattr(config, "bocha_api_keys", None),
            tavily_keys=getattr(config, "tavily_api_keys", None),
            anspire_keys=getattr(config, "anspire_api_keys", None),
            brave_keys=getattr(config, "brave_api_keys", None),
            serpapi_keys=getattr(config, "serpapi_keys", None),
            minimax_keys=getattr(config, "minimax_api_keys", None),
            searxng_base_urls=getattr(config, "searxng_base_urls", None),
            searxng_public_instances_enabled=getattr(
                config,
                "searxng_public_instances_enabled",
                True,
            ),
            news_max_age_days=getattr(config, "news_max_age_days", 3),
            news_strategy_profile=getattr(config, "news_strategy_profile", "short"),
        )

    analyzer = None
    if has_configured_llm_runtime(config):
        analyzer = StockReportAnalyzer(config=config)
        if not analyzer.is_available():
            logger.warning("LLM analyzer initialized but not available (check LLM_MODEL / LLM_API_KEY)")

    return notifier, analyzer, search_service

# -*- coding: utf-8 -*-
"""Search service singleton factory."""

import threading
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .service import SearchService

_search_service: Optional["SearchService"] = None
_search_service_lock = threading.Lock()


def _resolve_search_service_class():
    """Resolve SearchService via the public shim so tests can patch it."""
    import finance_analysis.search as search_shim
    return search_shim.SearchService


def get_search_service() -> "SearchService":
    """获取搜索服务单例"""
    global _search_service

    if _search_service is None:
        with _search_service_lock:
            if _search_service is None:
                from finance_analysis.search.config import get_search_config
                config = get_search_config()
                search_service_cls = _resolve_search_service_class()

                _search_service = search_service_cls(
                    bocha_keys=config.bocha_api_keys,
                    tavily_keys=config.tavily_api_keys,
                    anspire_keys=config.anspire_api_keys,
                    brave_keys=config.brave_api_keys,
                    serpapi_keys=config.serpapi_keys,
                    minimax_keys=config.minimax_api_keys,
                    searxng_base_urls=config.searxng_base_urls,
                    searxng_public_instances_enabled=config.searxng_public_instances_enabled,
                    news_max_age_days=config.news_max_age_days,
                    news_strategy_profile=getattr(config, "news_strategy_profile", "short"),
                )

    return _search_service


def reset_search_service() -> None:
    """重置搜索服务（用于测试）"""
    global _search_service
    with _search_service_lock:
        _search_service = None

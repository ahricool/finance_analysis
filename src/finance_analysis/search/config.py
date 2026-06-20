# -*- coding: utf-8 -*-
"""Search-owned configuration and news window helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import logging
from typing import Dict, List, Optional
from urllib.parse import urlparse

from finance_analysis.config.env_parsing import env_bool, env_list

logger = logging.getLogger(__name__)

NEWS_STRATEGY_WINDOWS: Dict[str, int] = {
    "ultra_short": 1,
    "short": 3,
    "medium": 7,
    "long": 30,
}


def normalize_news_strategy_profile(value: Optional[str]) -> str:
    candidate = (value or "short").strip().lower()
    return candidate if candidate in NEWS_STRATEGY_WINDOWS else "short"


def resolve_news_window_days(news_max_age_days: int, news_strategy_profile: Optional[str]) -> int:
    profile = normalize_news_strategy_profile(news_strategy_profile)
    profile_days = NEWS_STRATEGY_WINDOWS.get(profile, NEWS_STRATEGY_WINDOWS["short"])
    return max(1, min(max(1, int(news_max_age_days)), profile_days))


def _resolve_searxng_base_urls(raw_urls: List[str]) -> List[str]:
    valid_urls: list[str] = []
    invalid_urls: list[str] = []
    for url in raw_urls:
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            valid_urls.append(url)
        else:
            invalid_urls.append(url)
    if invalid_urls:
        logger.warning("SEARXNG_BASE_URLS contains invalid URLs and they were ignored: %s", ", ".join(invalid_urls[:3]))
    return valid_urls


@dataclass
class SearchConfig:
    anspire_api_keys: List[str] = field(default_factory=list)
    bocha_api_keys: List[str] = field(default_factory=list)
    minimax_api_keys: List[str] = field(default_factory=list)
    tavily_api_keys: List[str] = field(default_factory=list)
    brave_api_keys: List[str] = field(default_factory=list)
    serpapi_keys: List[str] = field(default_factory=list)
    searxng_base_urls: List[str] = field(default_factory=list)
    searxng_public_instances_enabled: bool = True
    news_max_age_days: int = 3
    news_strategy_profile: str = "short"

    def has_searxng_enabled(self) -> bool:
        return bool(self.searxng_base_urls) or bool(self.searxng_public_instances_enabled)

    def has_search_capability_enabled(self) -> bool:
        return bool(
            self.anspire_api_keys
            or self.bocha_api_keys
            or self.minimax_api_keys
            or self.tavily_api_keys
            or self.brave_api_keys
            or self.serpapi_keys
            or self.has_searxng_enabled()
        )


@lru_cache(maxsize=1)
def get_search_config() -> SearchConfig:
    return SearchConfig(
        anspire_api_keys=env_list("ANSPIRE_API_KEYS"),
        bocha_api_keys=env_list("BOCHA_API_KEYS"),
        minimax_api_keys=env_list("MINIMAX_API_KEYS"),
        tavily_api_keys=env_list("TAVILY_API_KEYS"),
        brave_api_keys=env_list("BRAVE_API_KEYS"),
        serpapi_keys=env_list("SERPAPI_API_KEYS"),
        searxng_base_urls=_resolve_searxng_base_urls(env_list("SEARXNG_BASE_URLS")),
        searxng_public_instances_enabled=env_bool("SEARXNG_PUBLIC_INSTANCES_ENABLED", True),
    )

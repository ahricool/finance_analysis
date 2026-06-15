# -*- coding: utf-8 -*-
"""Backward-compatible shim for ``src.search`` package."""

from src.search import *  # noqa: F401,F403
from src.search import (
    BaseSearchProvider,
    SearchResponse,
    SearchResult,
    SearchService,
    fetch_url_content,
    get_search_service,
    reset_search_service,
)

__all__ = [
    "BaseSearchProvider",
    "SearchResponse",
    "SearchResult",
    "SearchService",
    "fetch_url_content",
    "get_search_service",
    "reset_search_service",
]

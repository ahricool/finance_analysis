# -*- coding: utf-8 -*-
"""Unified news search service package."""

from .base import BaseSearchProvider
from .factory import get_search_service, reset_search_service
from .http_utils import fetch_url_content
from .models import SearchResponse, SearchResult
from .service import SearchService

__all__ = [
    "BaseSearchProvider",
    "SearchResponse",
    "SearchResult",
    "SearchService",
    "fetch_url_content",
    "get_search_service",
    "reset_search_service",
]

# -*- coding: utf-8 -*-
"""Domain models for the US premarket news intelligence task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class NewsCandidate:
    """A persisted Longbridge news item prepared for LLM evaluation."""

    news_id_or_url: str
    title: str
    description: str
    url: str
    related_symbols: List[str]
    published_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None

    def to_prompt_dict(self) -> Dict[str, Any]:
        return {
            "news_id_or_url": self.news_id_or_url,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "related_symbols": self.related_symbols,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


@dataclass
class PremarketNewsSummary:
    """Aggregate result of one premarket news intelligence run."""

    started_at: datetime
    finished_at: datetime
    symbols: List[str]
    fetched_news_count: int = 0
    inserted_news_count: int = 0
    candidates_count: int = 0
    important_news: List[Dict[str, Any]] = field(default_factory=list)
    impact_results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    calendar_id: Optional[int] = None
    notification_sent: bool = False

    @property
    def symbols_count(self) -> int:
        return len(self.symbols)

    @property
    def has_system_error(self) -> bool:
        return bool(self.errors)

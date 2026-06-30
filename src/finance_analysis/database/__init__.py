# -*- coding: utf-8 -*-
"""Database package public surface (models, session, helpers)."""

from finance_analysis.database.base import Base, ensure_aware_datetime
from finance_analysis.database.session import DatabaseManager, get_db, persist_llm_usage
from finance_analysis.database.models import (
    AnalysisHistory,
    CalendarEntry,
    ConversationMessage,
    FinanceEvent,
    FundamentalSnapshot,
    LLMUsage,
    NewsIntel,
    Signal,
    StockDaily,
    StockHolding,
    TaskRecord,
    User,
    WatchListItem,
)
from finance_analysis.core.time import date_range_bounds_utc, utc_isoformat, utc_now

__all__ = [
    "AnalysisHistory",
    "Base",
    "CalendarEntry",
    "ConversationMessage",
    "DatabaseManager",
    "FinanceEvent",
    "FundamentalSnapshot",
    "LLMUsage",
    "NewsIntel",
    "Signal",
    "StockDaily",
    "StockHolding",
    "TaskRecord",
    "User",
    "WatchListItem",
    "date_range_bounds_utc",
    "ensure_aware_datetime",
    "get_db",
    "persist_llm_usage",
    "utc_isoformat",
    "utc_now",
]

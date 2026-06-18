# -*- coding: utf-8 -*-
"""Storage compatibility layer.

The concrete ORM models now live in ``src.models`` and database connection
management lives in ``src.db``. This module re-exports the historical public
surface so existing imports from ``src.storage`` keep working.
"""

from src.db.base import Base, ensure_aware_datetime
from src.db.session import DatabaseManager, get_db, persist_llm_usage
from src.models import (
    AnalysisHistory,
    BacktestResult,
    BacktestSummary,
    CalendarEntry,
    ConversationMessage,
    FinanceEvent,
    FundamentalSnapshot,
    LLMUsage,
    NewsIntel,
    PortfolioAccount,
    PortfolioCashLedger,
    PortfolioCorporateAction,
    PortfolioDailySnapshot,
    PortfolioFxRate,
    PortfolioPosition,
    PortfolioPositionLot,
    PortfolioTrade,
    StockDaily,
    StockHolding,
    User,
    WatchListItem,
)
from src.time_utils import date_range_bounds_utc, utc_isoformat, utc_now

__all__ = [
    "AnalysisHistory",
    "BacktestResult",
    "BacktestSummary",
    "Base",
    "CalendarEntry",
    "ConversationMessage",
    "DatabaseManager",
    "FinanceEvent",
    "FundamentalSnapshot",
    "LLMUsage",
    "NewsIntel",
    "PortfolioAccount",
    "PortfolioCashLedger",
    "PortfolioCorporateAction",
    "PortfolioDailySnapshot",
    "PortfolioFxRate",
    "PortfolioPosition",
    "PortfolioPositionLot",
    "PortfolioTrade",
    "StockDaily",
    "StockHolding",
    "User",
    "WatchListItem",
    "date_range_bounds_utc",
    "ensure_aware_datetime",
    "get_db",
    "persist_llm_usage",
    "utc_isoformat",
    "utc_now",
]

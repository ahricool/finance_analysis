# -*- coding: utf-8 -*-
"""ORM model exports."""

from finance_analysis.database.models.analysis import AnalysisHistory
from finance_analysis.database.models.backtest import BacktestEquity, BacktestRun, BacktestTrade
from finance_analysis.database.models.calendar import CalendarEntry
from finance_analysis.database.models.conversation import ConversationMessage, LLMUsage
from finance_analysis.database.models.etf_rotation import ETFMarketRotationSnapshot, ETFMomentumSnapshot
from finance_analysis.database.models.market_calendar import FinanceEvent
from finance_analysis.database.models.news import FundamentalSnapshot, NewsIntel
from finance_analysis.database.models.portfolio import (
    AccountCashBalance,
    Instrument,
    OptionContract,
    PortfolioAccount,
    Position,
)
from finance_analysis.database.models.quant import (
    DailyFeatureSnapshot, EventFeatureDaily, IntradayConfirmation, MarketEvent,
    MarketRegimeSnapshot, ModelDefinition, ModelPrediction, ModelPublication, ModelRun,
    ModelSignal, PortfolioRecommendation, PortfolioRecommendationItem, QuantDatasetSnapshot,
    QuantUniverse, QuantUniverseMember, SectorRegimeSnapshot,
)
from finance_analysis.database.models.signal import Signal
from finance_analysis.database.models.scheduled_task_slot import ScheduledTaskSlot
from finance_analysis.database.models.stock import (
    MarketDataSymbol,
    StockAdjustmentFactor,
    StockCorporateAction,
    StockDaily,
    StockMinute,
)
from finance_analysis.database.models.task import TaskRecord
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot, TrendFollowingSummary
from finance_analysis.database.models.user import User
from finance_analysis.database.models.watch_list import WatchListItem

__all__ = [
    "AnalysisHistory",
    "AccountCashBalance",
    "BacktestEquity",
    "BacktestRun",
    "BacktestTrade",
    "CalendarEntry",
    "ConversationMessage",
    "ETFMomentumSnapshot",
    "ETFMarketRotationSnapshot",
    "FinanceEvent",
    "FundamentalSnapshot",
    "LLMUsage",
    "Instrument",
    "MarketDataSymbol",
    "NewsIntel",
    "OptionContract",
    "PortfolioAccount",
    "Position",
    "QuantUniverse", "QuantUniverseMember", "QuantDatasetSnapshot", "MarketRegimeSnapshot",
    "SectorRegimeSnapshot", "MarketEvent", "EventFeatureDaily", "DailyFeatureSnapshot",
    "ModelDefinition", "ModelRun", "ModelPublication", "ModelPrediction", "ModelSignal",
    "PortfolioRecommendation", "PortfolioRecommendationItem", "IntradayConfirmation",
    "Signal",
    "ScheduledTaskSlot",
    "StockAdjustmentFactor",
    "StockCorporateAction",
    "StockDaily",
    "StockMinute",
    "TaskRecord",
    "TrendFollowingSnapshot",
    "TrendFollowingSummary",
    "User",
    "WatchListItem",
]

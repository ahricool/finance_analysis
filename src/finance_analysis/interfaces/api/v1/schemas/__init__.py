# -*- coding: utf-8 -*-
"""
===================================
API v1 Schemas 模块初始化
===================================

职责：
1. 导出所有 Pydantic 模型
"""

from finance_analysis.interfaces.api.v1.schemas.common import (
    RootResponse,
    HealthResponse,
    ErrorResponse,
    SuccessResponse,
)
from finance_analysis.interfaces.api.v1.schemas.analysis import (
    AnalyzeRequest,
    AnalysisResultResponse,
    TaskAccepted,
    BatchTaskAcceptedResponse,
    TaskStatus,
)
from finance_analysis.interfaces.api.v1.schemas.history import (
    HistoryItem,
    HistoryListResponse,
    DeleteHistoryRequest,
    DeleteHistoryResponse,
    NewsIntelItem,
    NewsIntelResponse,
    AnalysisReport,
    ReportMeta,
    ReportSummary,
    ReportStrategy,
    ReportDetails,
)
from finance_analysis.interfaces.api.v1.schemas.stocks import (
    StockQuote,
    StockHistoryResponse,
    KLineData,
)

__all__ = [
    # common
    "RootResponse",
    "HealthResponse",
    "ErrorResponse",
    "SuccessResponse",
    # analysis
    "AnalyzeRequest",
    "AnalysisResultResponse",
    "TaskAccepted",
    "BatchTaskAcceptedResponse",
    "TaskStatus",
    # history
    "HistoryItem",
    "HistoryListResponse",
    "DeleteHistoryRequest",
    "DeleteHistoryResponse",
    "NewsIntelItem",
    "NewsIntelResponse",
    "AnalysisReport",
    "ReportMeta",
    "ReportSummary",
    "ReportStrategy",
    "ReportDetails",
    # stocks
    "StockQuote",
    "StockHistoryResponse",
    "KLineData",
]
"""API v1 schemas."""

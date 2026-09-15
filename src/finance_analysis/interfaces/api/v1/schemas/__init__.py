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
    # stocks
    "StockQuote",
    "StockHistoryResponse",
    "KLineData",
]
"""API v1 schemas."""

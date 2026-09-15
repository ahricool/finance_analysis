# -*- coding: utf-8 -*-
"""
===================================
API v1 Endpoints 模块初始化
===================================

职责：
1. 声明所有 endpoint 路由模块
"""

from finance_analysis.interfaces.api.v1.endpoints import (
    stocks,
    auth,
    usage,
)
__all__ = [
    "stocks",
    "auth",
    "usage",
]

# -*- coding: utf-8 -*-
"""
===================================
API v1 路由聚合
===================================

职责：
1. 聚合 v1 版本的所有 endpoint 路由
2. 统一添加 /api/v1 前缀
"""

from fastapi import APIRouter

from finance_analysis.interfaces.api.v1.endpoints import (  # pragma: allowlist secret
    notifications,
    crypto,
    auth,
    timeline,
    celery_demo,
    etf_rotation,
    market_data,
    macro,
    quant,
    stocks,
    tasks,
    trend_following,
    usage,
    watch_list,
)

# 创建 v1 版本主路由
router = APIRouter(prefix="/api/v1")

router.include_router(auth.router, prefix="/auth", tags=["Auth"])

router.include_router(stocks.router, prefix="/stocks", tags=["Stocks"])

router.include_router(
    market_data.router,
    prefix="/market-data",
    tags=["MarketData"],
)

router.include_router(usage.router, prefix="/usage", tags=["Usage"])

router.include_router(
    watch_list.router,
    prefix="/watch-list",
    tags=["WatchList"],
)

router.include_router(
    timeline.router,
    prefix="/timeline",
    tags=["Timeline"],
)

router.include_router(
    celery_demo.router,
    prefix="/celery",
    tags=["Celery"],
)

router.include_router(
    tasks.router,
    prefix="/tasks",
    tags=["Tasks"],
)

router.include_router(quant.router, prefix="/quant", tags=["Quant"])

router.include_router(etf_rotation.router, prefix="/etf-rotation", tags=["ETF Rotation"])

router.include_router(trend_following.router, prefix="/trend-following", tags=["Trend Following"])

router.include_router(crypto.router, prefix="/crypto", tags=["Crypto"])

router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])

from .endpoints import market_structure
router.include_router(market_structure.router, prefix="/market-structure", tags=["Market Structure"])

router.include_router(macro.router, prefix="/macro", tags=["US Macro"])

from .endpoints import industry_strength
router.include_router(industry_strength.router, prefix="/industry-strength", tags=["Industry Strength"])

from .endpoints import holdings
router.include_router(holdings.router, prefix="/holdings", tags=["Holdings"])

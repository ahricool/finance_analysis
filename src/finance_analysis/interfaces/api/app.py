# -*- coding: utf-8 -*-
"""
===================================
FastAPI 应用工厂模块
===================================

职责：
1. 创建和配置 FastAPI 应用实例
2. 配置 CORS 中间件
3. 注册路由和异常处理器
4. 提供后端 API 路由

使用方式：
    from finance_analysis.interfaces.api.app import create_app
    app = create_app()
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from finance_analysis.core.paths import ensure_data_directories
from finance_analysis.interfaces.api.v1 import api_v1_router
from finance_analysis.interfaces.api.middlewares.auth import add_auth_middleware
from finance_analysis.interfaces.api.middlewares.error_handler import add_error_handlers
from finance_analysis.interfaces.api.v1.schemas.common import HealthResponse
from finance_analysis.config import load_env
from finance_analysis.core.logging import ensure_backend_logging
from finance_analysis.core.time import utc_isoformat, utc_now


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Initialize and release shared services for the app lifecycle.

    Periodic scheduling now runs in a dedicated Celery Beat container; the API
    process no longer starts an in-process scheduler.
    """
    load_env()
    ensure_data_directories()
    ensure_backend_logging(service="server", log_prefix="web_server")
    yield


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用实例

    Returns:
        配置完成的 FastAPI 应用实例
    """
    # 创建 FastAPI 实例
    app = FastAPI(
        title="Finance Analysis API",
        description=(
            "Finance Analysis：多市场（A 股 / 港股 / 美股）股票智能分析 API\n\n"
            "## 功能模块\n"
            "- 股票分析：触发 AI 智能分析\n"
            "- 历史记录：查询历史分析报告\n"
            "- 股票数据：获取行情数据\n\n"
            "## 认证方式\n"
            "支持可选的运行时认证（通过 WebUI 设置页面启用/关闭）"
        ),
        version="1.0.0",
        lifespan=app_lifespan,
    )

    # ============================================================
    # CORS 配置
    # ============================================================

    allowed_origins = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()]

    # 允许所有来源（开发/演示用）
    allow_all_origins = os.environ.get("CORS_ALLOW_ALL", "").lower() == "true"
    allow_credentials = not allow_all_origins
    if allow_all_origins:
        allowed_origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    add_auth_middleware(app)

    # ============================================================
    # 注册路由
    # ============================================================

    app.include_router(api_v1_router)
    add_error_handlers(app)

    @app.get(
        "/status",
        response_model=HealthResponse,
        tags=["Health"],
        summary="健康检查",
        description="用于负载均衡器或监控系统检查服务状态",
    )
    async def health_check() -> HealthResponse:
        """健康检查接口"""
        return HealthResponse(status="ok", timestamp=utc_isoformat(utc_now()))

    return app


# 默认应用实例（供 uvicorn 直接使用）
app = create_app()

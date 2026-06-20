# -*- coding: utf-8 -*-
"""
===================================
FastAPI 应用工厂模块
===================================

职责：
1. 创建和配置 FastAPI 应用实例
2. 配置 CORS 中间件
3. 注册路由和异常处理器
4. 托管前端静态文件（生产模式）

使用方式：
    from finance_analysis.interfaces.api.app import create_app
    app = create_app()
"""

import logging
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Match src="/assets/foo.js" / href="/assets/foo.css" produced by the
# vite build. Used by the startup self-check to surface packaging
# mismatches early (see GitHub #1064 / #1065 / #1050).
_INDEX_ASSET_REF_PATTERN = re.compile(
    r"""(?:src|href)\s*=\s*["'](/assets/[^"']+)["']""",
    re.IGNORECASE,
)
_SAFE_MISSING_ASSET_MEDIA_TYPES = frozenset({"text/css", "text/javascript"})


def _check_frontend_assets_consistency(static_dir: Path) -> List[str]:
    """
    Verify that ``index.html`` only references assets that actually exist
    under ``static_dir``. Returns the list of missing references; an empty
    list means the bundle is consistent.

    Logs an actionable error when a mismatch is detected so the root cause
    is visible in application logs instead of surfacing as a silent
    blank page.
    """
    index_html = static_dir / "index.html"
    if not index_html.is_file():
        return []
    try:
        html = index_html.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Failed to read %s for asset check: %s", index_html, exc)
        return []

    missing: List[str] = []
    for match in _INDEX_ASSET_REF_PATTERN.finditer(html):
        ref = match.group(1)
        candidate = static_dir / ref.lstrip("/")
        if not candidate.is_file() and ref not in missing:
            missing.append(ref)

    if missing:
        logger.error(
            "Frontend bundle is inconsistent: index.html references %d asset(s) "
            "that are not present on disk under %s. This will surface as a "
            "blank page in the browser (see GitHub #1064 / #1065). "
            "Missing: %s. Re-run the frontend build and make sure the packaging "
            "step copies the freshly generated static/ directory.",
            len(missing),
            static_dir,
            ", ".join(missing),
        )
    return missing


def _resolve_asset_path(assets_dir: Path, asset_path: str) -> Optional[Path]:
    """Resolve a requested asset path while keeping it confined to assets_dir."""
    decoded_path = unquote(asset_path)
    if not decoded_path or decoded_path.startswith(("/", "\\")):
        return None
    if "\x00" in decoded_path:
        return None
    if "\\" in decoded_path:
        return None
    if ":" in decoded_path.split("/", 1)[0]:
        return None

    assets_root = assets_dir.resolve()
    candidate = (assets_root / decoded_path).resolve()
    if not candidate.is_relative_to(assets_root):
        return None
    return candidate


def _missing_asset_media_type(asset_path: str) -> str:
    """Return a safe media type for a missing asset response."""
    content_type, _ = mimetypes.guess_type(asset_path)
    if content_type in _SAFE_MISSING_ASSET_MEDIA_TYPES:
        return content_type
    return "text/plain"


from finance_analysis.interfaces.api.v1 import api_v1_router
from finance_analysis.interfaces.api.middlewares.auth import add_auth_middleware
from finance_analysis.interfaces.api.middlewares.error_handler import add_error_handlers
from finance_analysis.interfaces.api.v1.schemas.common import HealthResponse
from finance_analysis.config import load_env
from finance_analysis.core.logging import ensure_backend_logging
from finance_analysis.tasks.scheduler import (
    start_embedded_analysis_scheduler,
    shutdown_embedded_analysis_scheduler,
)
from finance_analysis.core.time import utc_isoformat, utc_now


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Initialize and release shared services for the app lifecycle."""
    load_env()
    ensure_backend_logging(service="server", log_prefix="web_server")
    analysis_scheduler = start_embedded_analysis_scheduler()
    app.state.analysis_scheduler = analysis_scheduler
    try:
        yield
    finally:
        shutdown_embedded_analysis_scheduler(analysis_scheduler)
        if hasattr(app.state, "analysis_scheduler"):
            delattr(app.state, "analysis_scheduler")


def create_app(static_dir: Optional[Path] = None) -> FastAPI:
    """
    创建并配置 FastAPI 应用实例

    Args:
        static_dir: 静态文件目录路径（可选，默认为项目根目录下的 static）

    Returns:
        配置完成的 FastAPI 应用实例
    """
    # 默认静态文件目录
    if static_dir is None:
        static_dir = Path(__file__).parent.parent / "static"

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

    allowed_origins = [
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]

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

    # ============================================================
    # 根路由和健康检查
    # ============================================================

    has_frontend = static_dir.exists() and (static_dir / "index.html").exists()

    if has_frontend:
        # Surface bundle inconsistencies as soon as the app starts so that
        # blank-page reports (#1064 / #1065 / #1050) can be diagnosed from
        # logs instead of via browser devtools.
        _check_frontend_assets_consistency(static_dir)

        @app.get("/", include_in_schema=False)
        async def root():
            """根路由 - 返回前端页面"""
            return FileResponse(static_dir / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def root():
            """根路由 - 前端未构建时返回引导页面"""
            return HTTPException(status_code=404)

    @app.get(
        "/api/health",
        response_model=HealthResponse,
        tags=["Health"],
        summary="健康检查",
        description="用于负载均衡器或监控系统检查服务状态",
    )
    async def health_check() -> HealthResponse:
        """健康检查接口"""
        return HealthResponse(status="ok", timestamp=utc_isoformat(utc_now()))

    # ============================================================
    # 静态文件托管（前端 SPA）
    # ============================================================

    if has_frontend:
        # Serve `/assets/*` explicitly so that misses return a plain-text
        # 404 with the correct Content-Type instead of the default JSON
        # error response. JSON for a JS/CSS request is what masked the
        # blank-page root cause in #1064; here we make it obvious that the
        # static file simply does not exist on disk.
        assets_dir = static_dir / "assets"

        assets_static_files = StaticFiles(directory=str(assets_dir), check_dir=False)
        assets_root = assets_dir.resolve()

        @app.api_route(
            "/assets/{asset_path:path}",
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )
        async def serve_asset(request: Request, asset_path: str):
            file_path = _resolve_asset_path(assets_dir, asset_path)
            if file_path is None:
                return Response(
                    content="not found",
                    status_code=404,
                    media_type="text/plain",
                )
            if file_path.is_file():
                relative_path = file_path.relative_to(assets_root).as_posix()
                return await assets_static_files.get_response(relative_path, request.scope)
            return Response(
                content="asset not found",
                status_code=404,
                media_type=_missing_asset_media_type(asset_path),
            )

        # SPA 路由回退
        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(request: Request, full_path: str):
            """SPA 路由回退 - 非 API 路由返回 index.html"""
            if full_path == "api" or full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404, content={"error": "not_found", "message": f"API endpoint /{full_path} not found"}
                )

            # Reuse the same containment check as /assets/* so that requests
            # like `/%2e%2e/%2e%2e/etc/passwd` cannot escape static_dir via
            # the SPA fallback. Starlette's :path converter does not collapse
            # `..` segments, so static_dir / full_path can resolve outside
            # the bundle root if served unchecked.
            file_path = _resolve_asset_path(static_dir, full_path) if full_path else None
            if file_path is not None and file_path.is_file():
                # Issue #520: Explicitly resolve MIME type to avoid
                # browsers rejecting JS modules served as text/plain.
                content_type, _ = mimetypes.guess_type(str(file_path))
                return FileResponse(file_path, media_type=content_type)

            return FileResponse(static_dir / "index.html")

    return app


# 默认应用实例（供 uvicorn 直接使用）
app = create_app()

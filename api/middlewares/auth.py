# -*- coding: utf-8 -*-
"""Auth middleware: protect /api/v1/* routes with the session JWT cookie."""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth import COOKIE_NAME, parse_session_uid
from src.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

EXEMPT_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/lookup",
        "/api/v1/auth/status",
        "/api/health",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)


def _path_exempt(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in EXEMPT_PATHS


class AuthMiddleware(BaseHTTPMiddleware):
    """Require a valid JWT session for protected API routes."""

    async def dispatch(self, request: Request, call_next: Callable):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if _path_exempt(path) or not path.startswith("/api/v1/"):
            return await call_next(request)

        cookie_val = request.cookies.get(COOKIE_NAME)
        uid = parse_session_uid(cookie_val) if cookie_val else None
        if not uid:
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "Login required"},
            )

        try:
            user = UserRepository().get_by_uid(uid)
        except Exception:
            logger.exception("Failed to validate authenticated user")
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "Login required"},
            )

        if user is None:
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "Login required"},
            )

        request.state.uid = uid
        return await call_next(request)


def add_auth_middleware(app):
    """Add auth middleware to protect API routes."""
    app.add_middleware(AuthMiddleware)

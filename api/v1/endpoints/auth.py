# -*- coding: utf-8 -*-
"""Authentication endpoints for Web login."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from src.auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE_HOURS_DEFAULT,
    change_password,
    check_rate_limit,
    clear_rate_limit,
    create_session,
    get_client_ip,
    has_stored_password,
    is_auth_enabled,
    is_password_changeable,
    parse_session_user_uid,
    record_login_failure,
    rotate_session_secret,
    verify_stored_password,
)
from src.repositories.user_repo import DEFAULT_ADMIN_EMAIL, UserRepository

logger = logging.getLogger(__name__)

router = APIRouter()


def _default_user_uid() -> str | None:
    try:
        u = UserRepository().get_by_email(DEFAULT_ADMIN_EMAIL)
    except Exception:
        logger.warning("Failed to load default user", exc_info=True)
        return None
    return u.uid if u else None


class LoginRequest(BaseModel):
    """Login request body. For first-time setup use password + password_confirm."""

    model_config = {"populate_by_name": True}

    email: str = Field(default=DEFAULT_ADMIN_EMAIL, description="邮箱")
    password: str = Field(default="", description="登录密码")
    password_confirm: str | None = Field(default=None, alias="passwordConfirm", description="Confirm (first-time)")


class ChangePasswordRequest(BaseModel):
    """Change password request body."""

    model_config = {"populate_by_name": True}

    current_password: str = Field(default="", alias="currentPassword")
    new_password: str = Field(default="", alias="newPassword")
    new_password_confirm: str = Field(default="", alias="newPasswordConfirm")


def _cookie_params(request: Request) -> dict:
    """Build cookie params including Secure based on request."""
    secure = False
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        proto = request.headers.get("X-Forwarded-Proto", "").lower()
        secure = proto == "https"
    else:
        # Check URL scheme when not behind proxy
        secure = request.url.scheme == "https"

    try:
        max_age_hours = int(os.getenv("ADMIN_SESSION_MAX_AGE_HOURS", str(SESSION_MAX_AGE_HOURS_DEFAULT)))
    except ValueError:
        max_age_hours = SESSION_MAX_AGE_HOURS_DEFAULT
    max_age = max_age_hours * 3600

    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
        "max_age": max_age,
    }


def _password_set_for_response() -> bool:
    """True when at least one login credential exists (DB user or legacy file hash)."""
    try:
        if UserRepository().any_user_has_password():
            return True
    except Exception:
        logger.debug("UserRepository password check failed", exc_info=True)
    return has_stored_password()


def _set_session_cookie(response: Response, session_value: str, request: Request) -> None:
    """Attach the login session cookie to a response."""
    params = _cookie_params(request)
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_value,
        httponly=params["httponly"],
        samesite=params["samesite"],
        secure=params["secure"],
        path=params["path"],
        max_age=params["max_age"],
    )


def _get_auth_status_dict(request: Request | None = None) -> dict:
    """Helper to build consistent auth status response body."""
    auth_enabled = is_auth_enabled()
    logged_in = False
    user_payload = None
    if request:
        cookie_val = request.cookies.get(COOKIE_NAME)
        uid = parse_session_user_uid(cookie_val) if cookie_val else None
        if uid:
            try:
                u = UserRepository().get_by_uid(uid)
                if u is not None:
                    logged_in = True
                    user_payload = UserRepository().to_public_dict(u)
            except Exception:
                logger.warning("Failed to load user for auth status", exc_info=True)

    return {
        "authEnabled": auth_enabled,
        "loggedIn": logged_in,
        "passwordSet": _password_set_for_response(),
        "passwordChangeable": is_password_changeable(),
        "setupState": "enabled",
        "user": user_payload,
    }


@router.get(
    "/status",
    summary="Get auth status",
    description="Returns whether auth is enabled and if the current request is logged in.",
)
async def auth_status(request: Request):
    """Return authEnabled, loggedIn, passwordSet, passwordChangeable, setupState without requiring auth."""
    return _get_auth_status_dict(request)



@router.post(
    "/login",
    summary="Login or set initial password",
    description="Verify password and set session cookie. If password not set yet, accepts password+passwordConfirm.",
)
async def auth_login(request: Request, body: LoginRequest):
    """Verify password or set initial password, set cookie on success. Returns 401 or 429 on failure."""
    email = (body.email or "").strip()
    password = (body.password or "").strip()
    if not email:
        return JSONResponse(
            status_code=400,
            content={"error": "email_required", "message": "请输入邮箱"},
        )
    if not password:
        return JSONResponse(
            status_code=400,
            content={"error": "password_required", "message": "请输入密码"},
        )

    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "message": "Too many failed attempts. Please try again later.",
            },
        )

    repo = UserRepository()
    user = repo.get_by_email(email)
    if user is None:
        record_login_failure(ip)
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_credentials", "message": "邮箱或密码错误"},
        )

    if not user.password_hash:
        if user.email.lower() == DEFAULT_ADMIN_EMAIL and has_stored_password():
            if not verify_stored_password(password):
                record_login_failure(ip)
                return JSONResponse(
                    status_code=401,
                    content={"error": "invalid_password", "message": "密码错误"},
                )
        else:
            confirm = (body.password_confirm or "").strip()
            if password != confirm:
                record_login_failure(ip)
                return JSONResponse(
                    status_code=400,
                    content={"error": "password_mismatch", "message": "Passwords do not match"},
                )
        repo.set_plain_password(user.uid, password)
    else:
        if repo.verify_credentials(email, password) is None:
            record_login_failure(ip)
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_password", "message": "密码错误"},
            )

    clear_rate_limit(ip)
    session_val = create_session(user_uid=user.uid)
    if not session_val:
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Failed to create session"},
        )

    resp = JSONResponse(content={"ok": True})
    _set_session_cookie(resp, session_val, request)
    return resp


@router.post(
    "/change-password",
    summary="Change password",
    description="Change password. Requires valid session.",
)
async def auth_change_password(request: Request, body: ChangePasswordRequest):
    """Change password for the logged-in user."""
    if not is_password_changeable():
        return JSONResponse(
            status_code=400,
            content={"error": "not_changeable", "message": "Password cannot be changed via web"},
        )

    uid = parse_session_user_uid(request.cookies.get(COOKIE_NAME) or "")
    if not uid:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Login required"},
        )

    current = (body.current_password or "").strip()
    new_pwd = (body.new_password or "").strip()
    new_confirm = (body.new_password_confirm or "").strip()

    if not current:
        return JSONResponse(
            status_code=400,
            content={"error": "current_required", "message": "请输入当前密码"},
        )
    if new_pwd != new_confirm:
        return JSONResponse(
            status_code=400,
            content={"error": "password_mismatch", "message": "两次输入的新密码不一致"},
        )

    repo = UserRepository()
    user = repo.get_by_uid(uid)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Login required"},
        )
    if not repo.verify_plain_for_uid(user.uid, current):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_password", "message": "当前密码错误"},
        )

    repo.set_plain_password(uid, new_pwd)
    default_uid = _default_user_uid()
    if default_uid == uid and has_stored_password():
        err = change_password(current, new_pwd)
        if err:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_password", "message": err},
            )
    return Response(status_code=204)


@router.post(
    "/logout",
    summary="Logout",
    description="Clear session cookie.",
)
async def auth_logout(request: Request):
    """Clear session cookie."""
    if not rotate_session_secret():
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Failed to invalidate session"},
        )
    resp = Response(status_code=204)
    resp.delete_cookie(key=COOKIE_NAME, path="/")
    return resp

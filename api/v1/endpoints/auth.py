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
    JWT_EXPIRE_SECONDS,
    check_rate_limit,
    clear_rate_limit,
    create_session,
    get_client_ip,
    is_auth_enabled,
    is_password_changeable,
    parse_session_user_uid,
    record_login_failure,
    validate_password,
)
from src.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter()


class EmailLookupRequest(BaseModel):
    """Step 1: verify email is registered and whether password setup is needed."""

    email: str = Field(..., description="邮箱")


class LoginRequest(BaseModel):
    """Login request body. First-time setup uses password + password_confirm."""

    model_config = {"populate_by_name": True}

    email: str = Field(..., description="邮箱")
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
        secure = request.url.scheme == "https"

    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
        "max_age": JWT_EXPIRE_SECONDS,
    }


def _password_set_for_response() -> bool:
    """True when at least one user has a password in the database."""
    try:
        return UserRepository().any_user_has_password()
    except Exception:
        logger.debug("UserRepository password check failed", exc_info=True)
        return False


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
    "/lookup",
    summary="Lookup email for login step",
    description="Step 1: check whether the email is registered and if first-time password setup is required.",
)
async def auth_lookup(request: Request, body: EmailLookupRequest):
    """Return needsPasswordSetup for a registered email."""
    email = (body.email or "").strip()
    if not email:
        return JSONResponse(
            status_code=400,
            content={"error": "email_required", "message": "请输入邮箱"},
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
    needs_setup = repo.user_needs_password_setup(email)
    if needs_setup is None:
        record_login_failure(ip)
        return JSONResponse(
            status_code=401,
            content={"error": "unknown_email", "message": "邮箱不存在"},
        )

    clear_rate_limit(ip)
    return {"ok": True, "needsPasswordSetup": needs_setup}


@router.post(
    "/login",
    summary="Login or set initial password",
    description="Verify password and set session cookie. First-time setup sets password only (requires re-login).",
)
async def auth_login(request: Request, body: LoginRequest):
    """Verify password or set initial password. Returns session cookie only for normal login."""
    email = (body.email or "").strip()
    password = (body.password or "").strip()
    if not email:
        return JSONResponse(
            status_code=400,
            content={"error": "email_required", "message": "请输入邮箱"},
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
        if not password:
            return JSONResponse(
                status_code=400,
                content={"error": "password_required", "message": "请设置密码"},
            )
        confirm = (body.password_confirm or "").strip()
        if not confirm:
            return JSONResponse(
                status_code=400,
                content={"error": "password_confirm_required", "message": "请确认密码"},
            )
        if password != confirm:
            record_login_failure(ip)
            return JSONResponse(
                status_code=400,
                content={"error": "password_mismatch", "message": "两次输入的密码不一致"},
            )
        pwd_err = validate_password(password)
        if pwd_err:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_password", "message": pwd_err},
            )
        repo.set_plain_password(user.uid, password)
        clear_rate_limit(ip)
        return JSONResponse(content={"ok": True, "requiresRelogin": True})

    if not password:
        return JSONResponse(
            status_code=400,
            content={"error": "password_required", "message": "请输入密码"},
        )

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

    pwd_err = validate_password(new_pwd)
    if pwd_err:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_password", "message": pwd_err},
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
    return Response(status_code=204)


@router.post(
    "/logout",
    summary="Logout",
    description="Clear session cookie.",
)
async def auth_logout(request: Request):
    """Clear session cookie."""
    resp = Response(status_code=204)
    resp.delete_cookie(key=COOKIE_NAME, path="/")
    return resp

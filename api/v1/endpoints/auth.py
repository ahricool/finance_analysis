# -*- coding: utf-8 -*-
"""Authentication endpoints for Web admin login."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from api.deps import get_system_config_service
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
    refresh_auth_state,
    rotate_session_secret,
    set_initial_password,
    verify_stored_password,
)
from src.config import Config, setup_env
from src.core.config_manager import ConfigManager
from src.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter()


def _ahri_user_uid() -> str | None:
    try:
        u = UserRepository().get_by_username("ahri")
    except Exception:
        logger.warning("Failed to load default admin user", exc_info=True)
        return None
    return u.uid if u else None


def _combined_password_exists() -> bool:
    if has_stored_password():
        return True
    try:
        return UserRepository().any_user_has_password()
    except Exception:
        return False


def _verify_current_password_any_source(current_password: str) -> bool:
    if verify_stored_password(current_password):
        return True
    try:
        return UserRepository().verify_plain_for_user("ahri", current_password)
    except Exception:
        logger.warning("Failed to verify default admin password", exc_info=True)
        return False


class LoginRequest(BaseModel):
    """Login request body. For first-time setup use password + password_confirm."""

    model_config = {"populate_by_name": True}

    username: str = Field(default="ahri", description="用户名")
    password: str = Field(default="", description="登录密码")
    password_confirm: str | None = Field(default=None, alias="passwordConfirm", description="Confirm (first-time)")


class ChangePasswordRequest(BaseModel):
    """Change password request body."""

    model_config = {"populate_by_name": True}

    current_password: str = Field(default="", alias="currentPassword")
    new_password: str = Field(default="", alias="newPassword")
    new_password_confirm: str = Field(default="", alias="newPasswordConfirm")


class AuthSettingsRequest(BaseModel):
    """Update auth enablement and initial password settings."""

    model_config = {"populate_by_name": True}

    auth_enabled: bool = Field(alias="authEnabled")
    password: str = Field(default="")
    password_confirm: str | None = Field(default=None, alias="passwordConfirm")
    current_password: str = Field(default="", alias="currentPassword")


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


def _apply_auth_enabled(enabled: bool, request: Request | None = None) -> bool:
    """Persist auth toggle to .env and reload runtime config."""
    manager_applied = False
    if request is not None:
        try:
            service = get_system_config_service(request)
            service.apply_simple_updates(
                updates=[("ADMIN_AUTH_ENABLED", "true" if enabled else "false")],
                mask_token="******",
            )
            manager_applied = True
        except Exception as exc:
            logger.warning(
                "Failed to apply auth toggle via shared SystemConfigService, falling back: %s",
                exc,
                exc_info=True,
            )
            manager_applied = False

    if not manager_applied:
        try:
            manager = ConfigManager()
            manager.apply_updates(
                updates=[("ADMIN_AUTH_ENABLED", "true" if enabled else "false")],
                sensitive_keys=set(),
                mask_token="******",
            )
            manager_applied = True
        except Exception as exc:
            logger.error("Failed to apply auth toggle via ConfigManager: %s", exc, exc_info=True)
            manager_applied = False

    if not manager_applied:
        return False

    Config.reset_instance()
    setup_env(override=True)
    refresh_auth_state()
    return True


def _password_set_for_response(auth_enabled: bool) -> bool:
    """True when at least one login credential exists (DB user or legacy file hash)."""
    if not auth_enabled:
        return False
    try:
        if UserRepository().any_user_has_password():
            return True
    except Exception:
        logger.debug("UserRepository password check failed", exc_info=True)
    return has_stored_password()


def _set_session_cookie(response: Response, session_value: str, request: Request) -> None:
    """Attach the admin session cookie to a response."""
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
    if auth_enabled and request:
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

    # setupState determination:
    # - enabled: auth is active
    # - password_retained: auth disabled but password exists
    # - no_password: auth disabled and no password exists
    try:
        any_user_pw = UserRepository().any_user_has_password()
    except Exception:
        any_user_pw = False
    if auth_enabled:
        setup_state = "enabled"
    elif has_stored_password() or any_user_pw:
        setup_state = "password_retained"
    else:
        setup_state = "no_password"

    return {
        "authEnabled": auth_enabled,
        "loggedIn": logged_in,
        "passwordSet": _password_set_for_response(auth_enabled),
        "passwordChangeable": is_password_changeable() if auth_enabled else False,
        "setupState": setup_state,
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
    "/settings",
    summary="Update auth settings",
    description=(
        "Enable or disable password login. When enabling without an existing password, "
        "password + passwordConfirm are required. When re-enabling with a stored password, "
        "currentPassword is required."
    ),
)
async def auth_update_settings(request: Request, body: AuthSettingsRequest):
    """Manage auth enablement from the settings page."""
    target_enabled = body.auth_enabled
    current_enabled = is_auth_enabled()
    combined_password_exists = _combined_password_exists()

    password = (body.password or "").strip()
    confirm = (body.password_confirm or "").strip()
    current_password = (body.current_password or "").strip()

    if target_enabled:
        if password or confirm:
            if combined_password_exists:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "password_already_set",
                        "message": "已存在管理员密码，请启用认证后通过修改密码功能更新",
                    },
                )
            if not password:
                return JSONResponse(
                    status_code=400,
                    content={"error": "password_required", "message": "请输入要设置的管理员密码"},
                )
            if password != confirm:
                return JSONResponse(
                    status_code=400,
                    content={"error": "password_mismatch", "message": "两次输入的密码不一致"},
                )
            err = set_initial_password(password)
            if err:
                return JSONResponse(
                    status_code=400,
                    content={"error": "invalid_password", "message": err},
                )
            ahri_uid = _ahri_user_uid()
            if ahri_uid:
                UserRepository().set_plain_password(ahri_uid, password)
        elif not combined_password_exists:
            return JSONResponse(
                status_code=400,
                content={"error": "password_required", "message": "开启密码登录前请先设置密码"},
            )
        else:
            # P1 Vulnerability Fix: Enforce current-password check independent of global cached flag
            # We must verify they actually possess a valid admin session, otherwise an attacker
            # could hit a race condition when auth becomes enabled mid-flight.
            # This triggers whenever trying to enable/keep enabled an existing auth setup.
            cookie_val = request.cookies.get(COOKIE_NAME)
            # if target_enabled is True here, they are requesting to enable or keep auth enabled
            is_valid_session = bool(parse_session_user_uid(cookie_val) if cookie_val else None)

            if not is_valid_session:
                if not current_password:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "current_required", "message": "重新开启认证前请输入当前密码"},
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
                if not _verify_current_password_any_source(current_password):
                    record_login_failure(ip)
                    return JSONResponse(
                        status_code=401,
                        content={"error": "invalid_password", "message": "当前密码错误"},
                    )
                clear_rate_limit(ip)
    else:
        if current_enabled:
            cookie_val = request.cookies.get(COOKIE_NAME)
            is_valid_session = bool(parse_session_user_uid(cookie_val) if cookie_val else None)

            if not is_valid_session:
                if not current_password:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "current_required", "message": "关闭认证前请输入当前密码"},
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
                if not _verify_current_password_any_source(current_password):
                    record_login_failure(ip)
                    return JSONResponse(
                        status_code=401,
                        content={"error": "invalid_password", "message": "当前密码错误"},
                    )
                clear_rate_limit(ip)

    if target_enabled != current_enabled:
        if not _apply_auth_enabled(target_enabled, request=request):
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to update auth settings"},
            )
        if not rotate_session_secret():
            rollback_ok = _apply_auth_enabled(current_enabled, request=request)
            if not rollback_ok:
                logger.error("Failed to roll back auth state after session secret rotation failure")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to rotate session secret"},
            )
    else:
        if not _apply_auth_enabled(target_enabled, request=request):
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to update auth settings"},
            )

    if target_enabled:
        cookie_val = request.cookies.get(COOKIE_NAME)
        session_uid = parse_session_user_uid(cookie_val) if cookie_val else None
        subject_uid = session_uid or _ahri_user_uid()
        if not subject_uid:
            rollback_ok = _apply_auth_enabled(current_enabled, request=request)
            if not rollback_ok:
                logger.error("Failed to roll back auth state after missing default user")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Default admin user missing"},
            )
        session_val = create_session(user_uid=subject_uid)
        if not session_val:
            rollback_ok = _apply_auth_enabled(current_enabled, request=request)
            if not rollback_ok:
                logger.error("Failed to roll back auth state after session creation failure")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to create session"},
            )
        # We manually set loggedIn=True because the cookie is being set in this response
        # and won't be visible in request.cookies until the NEXT request.
        content = _get_auth_status_dict(request)
        content["loggedIn"] = True
        resp = JSONResponse(content=content)
        _set_session_cookie(resp, session_val, request)
        return resp

    resp = JSONResponse(content=_get_auth_status_dict(request))
    resp.delete_cookie(key=COOKIE_NAME, path="/")
    return resp



@router.post(
    "/login",
    summary="Login or set initial password",
    description="Verify password and set session cookie. If password not set yet, accepts password+passwordConfirm.",
)
async def auth_login(request: Request, body: LoginRequest):
    """Verify password or set initial password, set cookie on success. Returns 401 or 429 on failure."""
    if not is_auth_enabled():
        return JSONResponse(
            status_code=400,
            content={"error": "auth_disabled", "message": "Authentication is not configured"},
        )

    username = (body.username or "ahri").strip() or "ahri"
    password = (body.password or "").strip()
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
    user = repo.get_by_username(username)
    if user is None:
        record_login_failure(ip)
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_credentials", "message": "用户不存在或密码错误"},
        )

    if not user.password_hash:
        confirm = (body.password_confirm or "").strip()
        if password != confirm:
            record_login_failure(ip)
            return JSONResponse(
                status_code=400,
                content={"error": "password_mismatch", "message": "Passwords do not match"},
            )
        repo.set_plain_password(user.uid, password)
    else:
        if repo.verify_credentials(username, password) is None:
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
    if not repo.verify_plain_for_user(user.username, current):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_password", "message": "当前密码错误"},
        )

    repo.set_plain_password(uid, new_pwd)
    ahri_uid = _ahri_user_uid()
    if ahri_uid == uid and has_stored_password():
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
    if is_auth_enabled() and not rotate_session_secret():
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Failed to invalidate session"},
        )
    resp = Response(status_code=204)
    resp.delete_cookie(key=COOKIE_NAME, path="/")
    return resp

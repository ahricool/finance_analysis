# -*- coding: utf-8 -*-
"""Authentication endpoints for web login."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from finance_analysis.users.avatar import AVATAR_FORMATS, MAX_AVATAR_BYTES, InvalidAvatar, normalize_avatar
from finance_analysis.users.auth import (
    COOKIE_NAME,
    JWT_EXPIRE_SECONDS,
    check_rate_limit,
    clear_rate_limit,
    create_session,
    get_client_ip,
    parse_session_uid,
    record_login_failure,
    validate_password,
)
from finance_analysis.database.repositories.user import VALID_GENDERS, UserRepository

logger = logging.getLogger(__name__)

router = APIRouter()


class EmailLookupRequest(BaseModel):
    """Step 1: verify email is registered and whether password setup is needed."""

    email: str = Field(..., description="Email")


class LoginRequest(BaseModel):
    """Login request body. First-time setup uses password + password_confirm."""

    model_config = {"populate_by_name": True}

    email: str = Field(..., description="Email")
    password: str = Field(default="", description="Password")
    password_confirm: str | None = Field(default=None, alias="passwordConfirm", description="Confirm (first-time)")


class ChangePasswordRequest(BaseModel):
    """Change password request body."""

    model_config = {"populate_by_name": True}

    current_password: str = Field(default="", alias="currentPassword")
    new_password: str = Field(default="", alias="newPassword")
    new_password_confirm: str = Field(default="", alias="newPasswordConfirm")


class NtfyProfileConfig(BaseModel):
    url: str = ""


class TelegramProfileConfig(BaseModel):
    bot_token: str = ""
    chat_id: str = ""


class NotificationProfileConfig(BaseModel):
    ntfy: list[NtfyProfileConfig] = Field(default_factory=lambda: [NtfyProfileConfig()])
    telegram: list[TelegramProfileConfig] = Field(default_factory=lambda: [TelegramProfileConfig()])


class ProfileUpdateRequest(BaseModel):
    username: str | None = None
    gender: str | None = None
    notification: NotificationProfileConfig | None = None


def _cookie_params(request: Request) -> dict:
    """Build cookie params, including Secure based on the current request."""
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        secure = request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    else:
        secure = request.url.scheme == "https"

    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
        "max_age": JWT_EXPIRE_SECONDS,
    }


def _set_session_cookie(response: Response, session_value: str, request: Request) -> None:
    """Attach the login session cookie to a response."""
    response.set_cookie(key=COOKIE_NAME, value=session_value, **_cookie_params(request))


def _get_auth_status_dict(request: Request | None = None) -> dict:
    """Build a consistent auth status response body."""
    logged_in = False
    user_payload = None
    if request:
        cookie_val = request.cookies.get(COOKIE_NAME)
        uid = parse_session_uid(cookie_val) if cookie_val else None
        if uid:
            try:
                repo = UserRepository()
                user = repo.get_by_uid(uid)
                if user is not None:
                    logged_in = True
                    user_payload = repo.to_public_dict(user)
            except Exception:
                logger.warning("Failed to load user for auth status", exc_info=True)

    return {
        "loggedIn": logged_in,
        "user": user_payload,
    }


def _get_request_uid(request: Request) -> int | None:
    state = getattr(request, "state", None)
    uid = getattr(state, "uid", None)
    if uid:
        return uid
    return parse_session_uid(request.cookies.get(COOKIE_NAME) or "")


def _notification_to_dict(notification: NotificationProfileConfig | None) -> dict[str, Any] | None:
    if notification is None:
        return None
    return {
        "ntfy": [{"url": item.url} for item in notification.ntfy],
        "telegram": [
            {"bot_token": item.bot_token, "chat_id": item.chat_id}
            for item in notification.telegram
        ],
    }


@router.get(
    "/status",
    summary="Get auth status",
    description="Returns whether auth is enabled and if the current request is logged in.",
)
async def auth_status(request: Request):
    """Return auth status without requiring auth."""
    return _get_auth_status_dict(request)


@router.get(
    "/profile",
    summary="Get current user profile",
    description="Returns editable profile fields for the current user.",
)
async def auth_profile(request: Request):
    uid = _get_request_uid(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})

    repo = UserRepository()
    user = repo.get_by_uid(uid)
    if user is None:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})
    return repo.to_profile_dict(user)


@router.patch(
    "/profile",
    summary="Update current user profile",
    description="Updates nickname, gender, and notification settings for the current user.",
)
async def auth_update_profile(request: Request, body: ProfileUpdateRequest):
    uid = _get_request_uid(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})

    username = body.username.strip() if body.username is not None else None
    if body.username is not None and not username:
        return JSONResponse(status_code=400, content={"error": "username_required", "message": "Nickname is required"})
    if username is not None and len(username) > 64:
        return JSONResponse(status_code=400, content={"error": "username_too_long", "message": "Nickname is too long"})
    if body.gender is not None and body.gender not in VALID_GENDERS:
        return JSONResponse(status_code=400, content={"error": "invalid_gender", "message": "Invalid gender"})

    repo = UserRepository()
    try:
        user = repo.update_profile(
            uid,
            username=username,
            gender=body.gender,
            notification=_notification_to_dict(body.notification),
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": "invalid_profile", "message": str(exc)})
    if user is None:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})
    return repo.to_profile_dict(user)


@router.post("/avatar", summary="Upload current user avatar")
async def auth_upload_avatar(request: Request, file: UploadFile = File(...)):
    uid = _get_request_uid(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})
    try:
        if file.content_type not in AVATAR_FORMATS:
            return JSONResponse(
                status_code=400, content={"error": "invalid_avatar_type", "message": "仅支持 JPEG、PNG 和 WebP"}
            )
        blob = await file.read(MAX_AVATAR_BYTES + 1)
        if len(blob) > MAX_AVATAR_BYTES:
            return JSONResponse(status_code=413, content={"error": "avatar_too_large", "message": "头像不能超过 5MB"})
        data = await run_in_threadpool(normalize_avatar, blob, file.content_type)
        repo = UserRepository()
        user = await run_in_threadpool(repo.save_avatar, uid, data)
        if user is None:
            return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})
        return {"ok": True, "user": repo.to_public_dict(user)}
    except InvalidAvatar as exc:
        return JSONResponse(status_code=400, content={"error": "invalid_avatar", "message": str(exc)})
    except Exception:
        logger.exception("Avatar upload failed for uid=%s", uid)
        return JSONResponse(
            status_code=500, content={"error": "avatar_save_failed", "message": "头像保存失败，请稍后重试"}
        )
    finally:
        await file.close()


@router.get("/avatar/{uid}.jpg", include_in_schema=False)
@router.get("/avatar/{uid}.webp", summary="Get current user avatar")
def auth_get_avatar(request: Request, uid: int):
    current_uid = _get_request_uid(request)
    if not current_uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})
    if current_uid != uid:
        return JSONResponse(status_code=403, content={"error": "forbidden", "message": "Avatar access denied"})
    try:
        avatar = UserRepository().get_avatar(uid)
    except Exception:
        logger.exception("Avatar read failed for uid=%s", uid)
        return JSONResponse(
            status_code=500, content={"error": "avatar_read_failed", "message": "头像读取失败，请稍后重试"}
        )
    if avatar is None:
        return JSONResponse(
            status_code=404,
            content={"error": "avatar_not_found", "message": "Avatar not found"},
            headers={"Cache-Control": "no-store"},
        )
    etag = f'"{avatar.version}"'
    # Revalidate private cached bytes so logout, replacement and deletion take effect.
    headers = {
        "Cache-Control": "private, no-cache",
        "ETag": etag,
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
    }
    candidates = [value.strip().removeprefix("W/") for value in request.headers.get("if-none-match", "").split(",")]
    if etag in candidates or "*" in candidates:
        return Response(status_code=304, headers=headers)
    return Response(content=avatar.data, media_type="image/webp", headers=headers)


@router.delete("/avatar", summary="Delete current user avatar")
def auth_delete_avatar(request: Request):
    uid = _get_request_uid(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})
    try:
        repo = UserRepository()
        user = repo.delete_avatar(uid)
        if user is None:
            return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})
        return {"ok": True, "user": repo.to_public_dict(user)}
    except Exception:
        logger.exception("Avatar deletion failed for uid=%s", uid)
        return JSONResponse(
            status_code=500, content={"error": "avatar_delete_failed", "message": "头像删除失败，请稍后重试"}
        )


@router.post(
    "/lookup",
    summary="Lookup email for login step",
    description="Step 1: check whether the email is registered and if first-time password setup is required.",
)
async def auth_lookup(request: Request, body: EmailLookupRequest):
    """Return needsPasswordSetup for a registered email."""
    email = (body.email or "").strip()
    if not email:
        return JSONResponse(status_code=400, content={"error": "email_required", "message": "Email is required"})

    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "message": "Too many failed attempts. Please try again later."},
        )

    repo = UserRepository()
    needs_setup = repo.user_needs_password_setup(email)
    if needs_setup is None:
        record_login_failure(ip)
        return JSONResponse(
            status_code=401,
            content={"error": "unknown_email", "message": "Email is not registered"},
        )

    clear_rate_limit(ip)
    return {"ok": True, "needsPasswordSetup": needs_setup}


@router.post(
    "/login",
    summary="Login or set initial password",
    description="Verify password and set session cookie. First-time setup sets password only.",
)
async def auth_login(request: Request, body: LoginRequest):
    """Verify password or set initial password."""
    email = (body.email or "").strip()
    password = (body.password or "").strip()
    if not email:
        return JSONResponse(status_code=400, content={"error": "email_required", "message": "Email is required"})

    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "message": "Too many failed attempts. Please try again later."},
        )

    repo = UserRepository()
    user = repo.get_by_email(email)
    if user is None:
        record_login_failure(ip)
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_credentials", "message": "Invalid email or password"},
        )
    if not password:
        return JSONResponse(
            status_code=400,
            content={"error": "password_required", "message": "Password is required"},
        )

    if not user.password_hash:
        confirm = (body.password_confirm or "").strip()
        if not confirm:
            return JSONResponse(
                status_code=400,
                content={"error": "password_confirm_required", "message": "Password confirmation is required"},
            )
        if password != confirm:
            record_login_failure(ip)
            return JSONResponse(
                status_code=400,
                content={"error": "password_mismatch", "message": "Passwords do not match"},
            )
        pwd_err = validate_password(password)
        if pwd_err:
            return JSONResponse(status_code=400, content={"error": "invalid_password", "message": pwd_err})

        repo.set_plain_password(user.id, password)
        clear_rate_limit(ip)
        return JSONResponse(content={"ok": True, "requiresRelogin": True})

    if repo.verify_credentials(email, password) is None:
        record_login_failure(ip)
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_password", "message": "Invalid password"},
        )

    clear_rate_limit(ip)
    try:
        session_val = create_session(uid=user.id)
    except ValueError:
        logger.exception("Failed to load auth session secret")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Failed to create session"},
        )
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
    uid = parse_session_uid(request.cookies.get(COOKIE_NAME) or "")
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})

    current = (body.current_password or "").strip()
    new_pwd = (body.new_password or "").strip()
    new_confirm = (body.new_password_confirm or "").strip()

    if not current:
        return JSONResponse(
            status_code=400,
            content={"error": "current_required", "message": "Current password is required"},
        )
    if new_pwd != new_confirm:
        return JSONResponse(
            status_code=400,
            content={"error": "password_mismatch", "message": "New passwords do not match"},
        )

    pwd_err = validate_password(new_pwd)
    if pwd_err:
        return JSONResponse(status_code=400, content={"error": "invalid_password", "message": pwd_err})

    repo = UserRepository()
    user = repo.get_by_uid(uid)
    if user is None:
        return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Login required"})
    if not repo.verify_plain_for_uid(user.id, current):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_password", "message": "Current password is incorrect"},
        )

    repo.set_plain_password(uid, new_pwd)
    return Response(status_code=204)


@router.post(
    "/logout",
    summary="Logout",
    description="Clear session cookie.",
)
async def auth_logout():
    """Clear session cookie."""
    resp = Response(status_code=204)
    resp.delete_cookie(key=COOKIE_NAME, path="/")
    return resp

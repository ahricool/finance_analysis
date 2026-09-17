# -*- coding: utf-8 -*-
"""Server-side Google OAuth Authorization Code Flow with PKCE."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.config import (  # pragma: allowlist secret
    GOOGLE_OAUTH_REVOKE_URL,
    SPREADSHEETS_READONLY_SCOPE,
    GoogleSheetsConfig,
    get_google_sheets_config,
)
from finance_analysis.integrations.google_sheets.credentials import (  # pragma: allowlist secret
    decrypt_credentials,
    encrypt_credentials,
    expiry_datetime,
)

OAUTH_STATE_TTL = timedelta(minutes=10)
OAUTH_STATE_PREFIX = "holdings:oauth:state:"


class GoogleOAuthError(RuntimeError):
    """OAuth protocol or configuration failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class OAuthState:
    uid: int
    source_id: int
    config_version: int
    return_path: str
    code_verifier: str


@dataclass(frozen=True, slots=True)
class GoogleTokens:
    refresh_token: str | None
    access_token: str | None
    expiry: str | None
    token_uri: str
    client_id: str
    scopes: tuple[str, ...]
    google_account_hint: str | None = None

    @property
    def has_offline_access(self) -> bool:
        return bool(self.refresh_token)


def _client_config(config: GoogleSheetsConfig) -> dict[str, Any]:
    return {
        "web": {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [config.redirect_uri],
        }
    }


def _flow(config: GoogleSheetsConfig, *, code_verifier: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(config),
        scopes=[SPREADSHEETS_READONLY_SCOPE],
        redirect_uri=config.redirect_uri,
    )
    if code_verifier:
        flow.code_verifier = code_verifier
    else:
        flow.code_verifier = secrets.token_urlsafe(64)
    return flow


def validate_return_path(value: str | None, *, config: GoogleSheetsConfig | None = None) -> str:
    resolved = config or get_google_sheets_config()
    path = (value or resolved.return_paths[0]).strip() or resolved.return_paths[0]
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise GoogleOAuthError("invalid_return_path", "返回地址仅允许站内路径")
    if path not in resolved.return_paths:
        raise GoogleOAuthError("invalid_return_path", "返回地址不在白名单内")
    return path


class GoogleOAuthService:
    def __init__(self, redis_client: Any, *, config: GoogleSheetsConfig | None = None) -> None:
        self.redis = redis_client
        self.config = config or get_google_sheets_config()

    def require_configured(self) -> GoogleSheetsConfig:
        if not self.config.configured:
            missing = ", ".join(self.config.missing)
            raise GoogleOAuthError("not_configured", f"Google OAuth 未配置: {missing}")
        return self.config

    def create_state(self, payload: OAuthState) -> str:
        self.require_configured()
        state = secrets.token_urlsafe(32)
        key = f"{OAUTH_STATE_PREFIX}{state}"
        body = {
            "uid": payload.uid,
            "source_id": payload.source_id,
            "config_version": payload.config_version,
            "return_path": payload.return_path,
            "code_verifier": payload.code_verifier,
        }
        stored = self.redis.set(key, json.dumps(body), nx=True, ex=int(OAUTH_STATE_TTL.total_seconds()))
        if not stored:
            raise GoogleOAuthError("state_conflict", "无法创建授权 state，请重试")
        return state

    def consume_state(self, state: str) -> OAuthState:
        if not state or not str(state).strip():
            raise GoogleOAuthError("invalid_state", "授权 state 无效，请重新连接")
        key = f"{OAUTH_STATE_PREFIX}{state.strip()}"
        raw = self.redis.getdel(key) if hasattr(self.redis, "getdel") else None
        if raw is None and hasattr(self.redis, "get"):
            pipe = getattr(self.redis, "pipeline", None)
            if callable(pipe):
                pipeline = self.redis.pipeline()
                pipeline.get(key)
                pipeline.delete(key)
                raw, _deleted = pipeline.execute()
            else:
                raw = self.redis.get(key)
                if raw is not None:
                    self.redis.delete(key)
        if raw is None:
            raise GoogleOAuthError("invalid_state", "授权 state 无效、过期或已使用，请重新连接")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return OAuthState(
            uid=int(data["uid"]),
            source_id=int(data["source_id"]),
            config_version=int(data["config_version"]),
            return_path=str(data["return_path"]),
            code_verifier=str(data["code_verifier"]),
        )

    def authorization_url(self, *, state: str, code_verifier: str) -> str:
        config = self.require_configured()
        flow = _flow(config, code_verifier=code_verifier)
        url, _state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return url

    def exchange_code(self, *, code: str, code_verifier: str) -> GoogleTokens:
        config = self.require_configured()
        if not code or not str(code).strip():
            raise GoogleOAuthError("invalid_code", "授权 code 无效，请重新连接")
        flow = _flow(config, code_verifier=code_verifier)
        try:
            flow.fetch_token(code=code.strip())
        except Exception as exc:
            raise GoogleOAuthError("oauth_exchange_failed", "Google 授权交换失败，请重新连接") from exc
        credentials = flow.credentials
        scopes = tuple(credentials.scopes or (SPREADSHEETS_READONLY_SCOPE,))
        if SPREADSHEETS_READONLY_SCOPE not in scopes:
            raise GoogleOAuthError("insufficient_scope", "未授予 spreadsheets.readonly")
        expiry = credentials.expiry.isoformat() if getattr(credentials, "expiry", None) else None
        return GoogleTokens(
            refresh_token=credentials.refresh_token,
            access_token=credentials.token,
            expiry=expiry,
            token_uri=credentials.token_uri or "https://oauth2.googleapis.com/token",
            client_id=credentials.client_id or config.client_id or "",
            scopes=scopes,
        )

    def credentials_from_blob(self, blob: bytes | str | None) -> Credentials | None:
        config = self.require_configured()
        payload = decrypt_credentials(blob, config=config)
        refresh = payload.get("refresh_token")
        if not refresh:
            return None
        expiry = expiry_datetime(payload.get("expiry"))
        return Credentials(
            token=payload.get("access_token"),
            refresh_token=refresh,
            token_uri=payload.get("token_uri") or "https://oauth2.googleapis.com/token",
            client_id=payload.get("client_id") or config.client_id,
            client_secret=config.client_secret,
            scopes=payload.get("scopes") or [SPREADSHEETS_READONLY_SCOPE],
            expiry=expiry.replace(tzinfo=None) if expiry is not None else None,
        )

    def refresh(self, blob: bytes | str | None) -> tuple[GoogleTokens, str]:
        """Refresh access token. Keep the previous refresh token when Google omits a new one."""

        config = self.require_configured()
        existing = decrypt_credentials(blob, config=config)
        credentials = self.credentials_from_blob(blob)
        if credentials is None or not credentials.refresh_token:
            raise GoogleOAuthError("needs_reauth", "缺少 refresh token，需要重新授权")
        try:
            credentials.refresh(GoogleAuthRequest())
        except Exception as exc:
            text = str(exc).lower()
            if "invalid_grant" in text or "revoked" in text:
                raise GoogleOAuthError("needs_reauth", "Google 授权已失效，需要重新连接") from exc
            raise GoogleOAuthError("token_refresh_failed", "刷新 Google 访问令牌失败") from exc
        refresh_token = credentials.refresh_token or existing.get("refresh_token")
        expiry = credentials.expiry.isoformat() if credentials.expiry else existing.get("expiry")
        tokens = GoogleTokens(
            refresh_token=refresh_token,
            access_token=credentials.token,
            expiry=expiry,
            token_uri=credentials.token_uri or existing.get("token_uri") or "https://oauth2.googleapis.com/token",
            client_id=credentials.client_id or existing.get("client_id") or config.client_id or "",
            scopes=tuple(credentials.scopes or existing.get("scopes") or (SPREADSHEETS_READONLY_SCOPE,)),
            google_account_hint=existing.get("google_account_hint"),
        )
        return tokens, encrypt_credentials(tokens.__dict__, config=config).decode("utf-8")

    def encrypt_tokens(self, tokens: GoogleTokens, *, previous: Mapping[str, Any] | None = None) -> bytes:
        payload = dict(tokens.__dict__)
        if previous:
            if not payload.get("refresh_token"):
                payload["refresh_token"] = previous.get("refresh_token")
            if not payload.get("google_account_hint"):
                payload["google_account_hint"] = previous.get("google_account_hint")
        return encrypt_credentials(payload, config=self.config)

    def revoke(self, blob: bytes | str | None) -> str:
        """Attempt Google revoke. Local disconnect is reported separately."""

        payload = decrypt_credentials(blob, config=self.config)
        token = payload.get("refresh_token") or payload.get("access_token")
        if not token:
            return "skipped_no_token"
        try:
            response = httpx.post(GOOGLE_OAUTH_REVOKE_URL, params={"token": token}, timeout=10.0)
        except Exception:
            return "revoke_request_failed"
        if response.status_code in {200, 400}:
            return "revoked_or_already_invalid"
        return f"revoke_http_{response.status_code}"


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def utc_timestamp() -> str:
    return utc_now().isoformat()

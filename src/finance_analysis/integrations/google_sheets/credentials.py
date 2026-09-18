# -*- coding: utf-8 -*-
"""Encrypt Google refresh tokens with a deployment-provided Fernet key."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from cryptography.fernet import Fernet, InvalidToken

from finance_analysis.integrations.google_sheets.config import GoogleSheetsConfig, get_google_sheets_config  # pragma: allowlist secret

STORED_CREDENTIAL_FIELDS = (
    "refresh_token",
    "access_token",
    "expiry",
    "token_uri",
    "client_id",
    "scopes",
    "google_account_hint",
)


class TokenKeyError(RuntimeError):
    """Raised when the deployment token key is missing or not a Fernet key."""


def _fernet(config: GoogleSheetsConfig | None = None) -> Fernet:
    resolved = config or get_google_sheets_config()
    key = (resolved.token_key or "").strip()
    if not key:
        raise TokenKeyError("GOOGLE_OAUTH_TOKEN_KEY is not configured")
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as exc:
        raise TokenKeyError("GOOGLE_OAUTH_TOKEN_KEY must be a url-safe Fernet key") from exc


def encrypt_credentials(payload: Mapping[str, Any], *, config: GoogleSheetsConfig | None = None) -> bytes:
    body = {key: payload.get(key) for key in STORED_CREDENTIAL_FIELDS if payload.get(key) is not None}
    return _fernet(config).encrypt(json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def decrypt_credentials(blob: bytes | str | None, *, config: GoogleSheetsConfig | None = None) -> dict[str, Any]:
    if blob in (None, "", b""):
        return {}
    raw = blob.encode("utf-8") if isinstance(blob, str) else blob
    try:
        decoded = json.loads(_fernet(config).decrypt(raw).decode("utf-8"))
    except InvalidToken as exc:
        raise TokenKeyError("stored Google credentials cannot be decrypted with the current key") from exc
    if not isinstance(decoded, dict):
        return {}
    return {key: decoded.get(key) for key in STORED_CREDENTIAL_FIELDS if decoded.get(key) is not None}


def expiry_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

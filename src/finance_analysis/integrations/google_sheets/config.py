# -*- coding: utf-8 -*-
"""Google Sheets OAuth configuration. Missing values are an explicit NOT_CONFIGURED state."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from finance_analysis.config.env_parsing import env_str  # pragma: allowlist secret

SPREADSHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_SHEETS_API_HOST = "sheets.googleapis.com"
ALLOWED_RETURN_PATHS = ("/market/holdings",)
DEFAULT_ACCOUNTS_RANGE = "Accounts"
DEFAULT_POSITIONS_RANGE = "Positions"


@dataclass(frozen=True, slots=True)
class GoogleSheetsConfig:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    token_key: str | None
    accounts_range: str
    positions_range: str
    return_paths: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return all((self.client_id, self.client_secret, self.redirect_uri, self.token_key))

    @property
    def missing(self) -> tuple[str, ...]:
        names = []
        if not self.client_id:
            names.append("GOOGLE_OAUTH_CLIENT_ID")
        if not self.client_secret:
            names.append("GOOGLE_OAUTH_CLIENT_SECRET")
        if not self.redirect_uri:
            names.append("GOOGLE_OAUTH_REDIRECT_URI")
        if not self.token_key:
            names.append("GOOGLE_OAUTH_TOKEN_KEY")
        return tuple(names)


def _return_paths(raw: str | None) -> tuple[str, ...]:
    if not raw or not raw.strip():
        return ALLOWED_RETURN_PATHS
    values = tuple(item.strip() for item in raw.split(",") if item.strip().startswith("/"))
    return values or ALLOWED_RETURN_PATHS


def validate_redirect_uri(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("GOOGLE_OAUTH_REDIRECT_URI must be an absolute http(s) URL without query")
    if not parsed.path.rstrip("/").endswith("/holdings/oauth/callback"):
        raise ValueError("GOOGLE_OAUTH_REDIRECT_URI must end with /holdings/oauth/callback")
    return value.rstrip("/")


@lru_cache(maxsize=1)
def get_google_sheets_config() -> GoogleSheetsConfig:
    redirect = env_str("GOOGLE_OAUTH_REDIRECT_URI") or None
    if redirect:
        redirect = validate_redirect_uri(redirect)
    return GoogleSheetsConfig(
        client_id=(env_str("GOOGLE_OAUTH_CLIENT_ID") or "").strip() or None,
        client_secret=(env_str("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip() or None,
        redirect_uri=redirect,
        token_key=(env_str("GOOGLE_OAUTH_TOKEN_KEY") or "").strip() or None,
        accounts_range=(env_str("GOOGLE_SHEETS_ACCOUNTS_RANGE") or DEFAULT_ACCOUNTS_RANGE).strip()
        or DEFAULT_ACCOUNTS_RANGE,
        positions_range=(env_str("GOOGLE_SHEETS_POSITIONS_RANGE") or DEFAULT_POSITIONS_RANGE).strip()
        or DEFAULT_POSITIONS_RANGE,
        return_paths=_return_paths(env_str("GOOGLE_OAUTH_RETURN_PATHS")),
    )


def reset_google_sheets_config() -> None:
    get_google_sheets_config.cache_clear()

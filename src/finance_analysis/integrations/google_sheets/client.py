# -*- coding: utf-8 -*-
"""Read-only Google Sheets client. Requests only Google API hosts, never user-supplied URLs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials

from finance_analysis.integrations.google_sheets.config import GOOGLE_SHEETS_API_HOST, get_google_sheets_config  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.oauth import GoogleOAuthError  # pragma: allowlist secret

SHEETS_VALUES_URL = "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchGet"
SHEETS_META_URL = "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
DEFAULT_TIMEZONE = "UTC"


class GoogleSheetsError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class SheetBatch:
    spreadsheet_id: str
    timezone: str
    title: str
    values: dict[str, list[list[Any]]]


def _assert_google_api_url(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host != GOOGLE_SHEETS_API_HOST:
        raise GoogleSheetsError("invalid_host", "refusing to request a non-Google Sheets API host")


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


class GoogleSheetsClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        http_client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = _sleep,
        max_retries: int = 3,
    ) -> None:
        self.credentials = credentials
        self._http = http_client
        self._sleeper = sleeper
        self.max_retries = max_retries

    def _access_token(self) -> str:
        if not self.credentials.token or self.credentials.expired:
            if not self.credentials.refresh_token:
                raise GoogleOAuthError("needs_reauth", "缺少 refresh token，需要重新授权")
            try:
                self.credentials.refresh(GoogleAuthRequest())
            except Exception as exc:
                text = str(exc).lower()
                if "invalid_grant" in text or "revoked" in text:
                    raise GoogleOAuthError("needs_reauth", "Google 授权已失效，需要重新连接") from exc
                raise GoogleSheetsError("token_refresh_failed", "刷新 Google 访问令牌失败", retryable=True) from exc
        if not self.credentials.token:
            raise GoogleOAuthError("needs_reauth", "Google 访问令牌不可用")
        return self.credentials.token

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        _assert_google_api_url(url)
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self._access_token()}"
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if self._http is None:
                    response = httpx.request(method, url, headers=headers, timeout=20.0, **kwargs)
                else:
                    response = self._http.request(method, url, headers=headers, timeout=20.0, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise GoogleSheetsError("network_error", "读取 Google Sheet 失败", retryable=True) from exc
                self._sleeper(delay)
                delay = min(delay * 2, 8.0)
                continue
            if response.status_code in {401, 403}:
                raise GoogleOAuthError("needs_reauth", "Google 拒绝访问该表格，需要重新授权")
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt >= self.max_retries:
                    raise GoogleSheetsError(
                        f"http_{response.status_code}",
                        "Google Sheets 暂时不可用",
                        retryable=True,
                    )
                self._sleeper(delay)
                delay = min(delay * 2, 8.0)
                continue
            if response.status_code >= 400:
                raise GoogleSheetsError(f"http_{response.status_code}", "Google Sheets 请求被拒绝")
            return response
        raise GoogleSheetsError("network_error", "读取 Google Sheet 失败", retryable=True) from last_error

    def fetch_batch(self, spreadsheet_id: str, ranges: Mapping[str, str]) -> SheetBatch:
        config = get_google_sheets_config()
        meta = self._request(
            "GET",
            SHEETS_META_URL.format(spreadsheet_id=spreadsheet_id),
            params={"fields": "properties.title,properties.timeZone,spreadsheetId"},
        ).json()
        timezone_name = str(meta.get("properties", {}).get("timeZone") or DEFAULT_TIMEZONE)
        try:
            ZoneInfo(timezone_name)
        except Exception:
            timezone_name = DEFAULT_TIMEZONE
        params = [
            ("majorDimension", "ROWS"),
            ("valueRenderOption", "UNFORMATTED_VALUE"),
            ("dateTimeRenderOption", "SERIAL_NUMBER"),
        ]
        for named_range in ranges.values():
            params.append(("ranges", named_range))
        payload = self._request(
            "GET",
            SHEETS_VALUES_URL.format(spreadsheet_id=spreadsheet_id),
            params=params,
        ).json()
        values: dict[str, list[list[Any]]] = {name: [] for name in ranges}
        by_range = {}
        for item in payload.get("valueRanges") or []:
            by_range[str(item.get("range") or "").split("!")[0].strip("'")] = item.get("values") or []
        for name, named_range in ranges.items():
            sheet_name = named_range.split("!")[0]
            values[name] = by_range.get(sheet_name) or by_range.get(named_range) or []
        if "Accounts" not in values:
            values["Accounts"] = values.get("accounts") or []
        if "Positions" not in values:
            values["Positions"] = values.get("positions") or []
        _ = config
        return SheetBatch(
            spreadsheet_id=str(meta.get("spreadsheetId") or spreadsheet_id),
            timezone=timezone_name,
            title=str(meta.get("properties", {}).get("title") or ""),
            values=values,
        )

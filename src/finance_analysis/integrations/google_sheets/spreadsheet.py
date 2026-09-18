# -*- coding: utf-8 -*-
"""Parse a spreadsheet ID from a pasted Google Sheets URL without fetching it."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")
_ALLOWED_HOSTS = {"docs.google.com"}


class SpreadsheetIdError(ValueError):
    """Raised when a pasted value is not a Google Sheets ID or docs.google.com URL."""


def parse_spreadsheet_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SpreadsheetIdError("spreadsheet_id is required")
    if _ID_RE.fullmatch(text):
        return text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"} or host not in _ALLOWED_HOSTS:
        raise SpreadsheetIdError("only a Google Sheets ID or docs.google.com spreadsheet URL is accepted")
    parts = [item for item in parsed.path.split("/") if item]
    try:
        index = parts.index("d")
        spreadsheet_id = parts[index + 1]
    except (ValueError, IndexError) as exc:
        raise SpreadsheetIdError("URL does not contain /spreadsheets/d/{id}") from exc
    if "spreadsheets" not in parts or not _ID_RE.fullmatch(spreadsheet_id):
        raise SpreadsheetIdError("URL does not contain a valid spreadsheet id")
    return spreadsheet_id

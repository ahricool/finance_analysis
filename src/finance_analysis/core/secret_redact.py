# -*- coding: utf-8 -*-
"""Redact OAuth/query secrets from logs without touching business payloads."""

from __future__ import annotations

import logging
import re
from typing import Any

_QUERY_SECRET_RE = re.compile(
    r"([?&](?:code|state|error_description|refresh_token|access_token|code_verifier)=)[^&\s]+",
    re.IGNORECASE,
)
_JSONISH_SECRET_RE = re.compile(
    r"(?i)(\"(?:refresh_token|access_token|id_token|code_verifier|authorization_code|oauth_state)\"\s*:\s*\")([^\"]*)(\")",
)
_BEARER_RE = re.compile(r"(?i)(bearer\s+)([a-z0-9._\-=]+)")
_REDACTED = r"\1[REDACTED]"


def redact_secrets(value: Any) -> str:
    text = "" if value is None else str(value)
    text = _QUERY_SECRET_RE.sub(_REDACTED, text)
    text = _JSONISH_SECRET_RE.sub(r"\1[REDACTED]\3", text)
    text = _BEARER_RE.sub(_REDACTED, text)
    return text


class SecretRedactFilter(logging.Filter):
    """Replace OAuth query and token fragments after the log record is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True
        redacted = redact_secrets(rendered)
        if redacted != rendered:
            record.msg = redacted
            record.args = ()
        return True

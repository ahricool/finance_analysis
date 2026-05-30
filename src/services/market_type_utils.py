# -*- coding: utf-8 -*-
"""Utilities for stock market classification."""

from __future__ import annotations

import re
from typing import Literal

MarketType = Literal["CN", "US", "HK"]
VALID_MARKET_TYPES: tuple[str, ...] = ("CN", "US", "HK")
DEFAULT_MARKET_TYPE: MarketType = "CN"

_MARKET_LABELS = {
    "CN": "A股",
    "US": "美股",
    "HK": "港股",
}


def normalize_market_type(value: str | None, code: str | None = None) -> MarketType:
    """Normalize a market type value, inferring from ``code`` when omitted."""
    text = (value or "").strip().upper()
    aliases = {
        "A": "CN",
        "A股": "CN",
        "CN": "CN",
        "CHINA": "CN",
        "ASHARE": "CN",
        "US": "US",
        "USA": "US",
        "美股": "US",
        "HK": "HK",
        "HKG": "HK",
        "港股": "HK",
    }
    if text in aliases:
        return aliases[text]  # type: ignore[return-value]
    return infer_market_type(code or "")


def infer_market_type(code: str) -> MarketType:
    """Infer market type from a stock code using common A/HK/US patterns."""
    text = (code or "").strip().upper()
    if not text:
        return DEFAULT_MARKET_TYPE
    if text.startswith("HK") or text.endswith(".HK"):
        return "HK"
    if re.fullmatch(r"\d{5}", text):
        return "HK"
    if re.fullmatch(r"\d{6}", text) or text.startswith(("SH", "SZ", "BJ")) or text.endswith((".SH", ".SZ", ".SS", ".BJ")):
        return "CN"
    if re.fullmatch(r"[A-Z]{1,5}(?:\.(?:US|[A-Z]))?", text):
        return "US"
    return DEFAULT_MARKET_TYPE


def market_type_label(value: str | None) -> str:
    """Return a Chinese display label for a normalized market type."""
    return _MARKET_LABELS.get((value or "").strip().upper(), _MARKET_LABELS[DEFAULT_MARKET_TYPE])

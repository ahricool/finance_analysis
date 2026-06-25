# -*- coding: utf-8 -*-
"""Utilities for stock market classification."""

from __future__ import annotations

import re
from typing import Literal

MarketType = Literal["CN", "US", "HK"]
VALID_MARKET_TYPES: tuple[str, ...] = ("CN", "US", "HK")
DEFAULT_MARKET_TYPE: MarketType = "CN"
MARKET_CURRENCY_MAP: dict[MarketType, str] = {
    "CN": "CNY",
    "US": "USD",
    "HK": "HKD",
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


def market_currency(market_type: str | None, code: str | None = None) -> str:
    """Return the settlement currency code inferred from a normalized market."""
    return MARKET_CURRENCY_MAP[normalize_market_type(market_type, code)]


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

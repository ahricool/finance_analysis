"""Instrument hints used to constrain financial report interpretation."""

import re

from finance_analysis.integrations.market_data.providers.us_index_mapping import (
    is_us_index_code,
)


def is_index_or_etf(stock_code: str, stock_name: str) -> bool:
    """Recognize index/fund symbols so issuer risks are not attributed to a fund."""
    code = (stock_code or "").strip().split(".")[0]
    if not code:
        return False
    if code.isdigit() and len(code) == 6 and code.startswith(("51", "52", "56", "58", "15", "16", "18")):
        return True
    if is_us_index_code(code):
        return True
    if re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", code) or code.lower().startswith("hk") or (code.isdigit() and len(code) == 5):
        return any(word in (stock_name or "").upper() for word in ("ETF", "FUND", "TRUST", "INDEX", "TRACKER", "UNIT"))
    return False

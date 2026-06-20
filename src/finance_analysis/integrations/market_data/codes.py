# -*- coding: utf-8 -*-
"""Stock code normalization and market classification utilities."""

from finance_analysis.integrations.market_data.providers.us_index_mapping import is_us_index_code, is_us_stock_code

ETF_PREFIXES = ("51", "52", "56", "58", "15", "16", "18")


def normalize_stock_code(stock_code: str) -> str:
    """
    Normalize stock code by stripping exchange prefixes/suffixes.

    Accepted formats and their normalized results:
    - '600519'      -> '600519'   (already clean)
    - 'SH600519'    -> '600519'   (strip SH prefix)
    - 'SZ000001'    -> '000001'   (strip SZ prefix)
    - 'BJ920748'    -> '920748'   (strip BJ prefix, BSE)
    - 'sh600519'    -> '600519'   (case-insensitive)
    - '600519.SH'   -> '600519'   (strip .SH suffix)
    - '000001.SZ'   -> '000001'   (strip .SZ suffix)
    - '920748.BJ'   -> '920748'   (strip .BJ suffix, BSE)
    - 'HK00700'     -> 'HK00700'  (keep HK prefix for HK stocks)
    - '1810.HK'     -> 'HK01810'  (normalize HK suffix to canonical prefix form)
    - 'AAPL'        -> 'AAPL'     (keep US stock ticker as-is)
    """
    code = stock_code.strip()
    upper = code.upper()

    if upper.startswith('HK') and not upper.startswith('HK.'):
        candidate = upper[2:]
        if candidate.isdigit() and 1 <= len(candidate) <= 5:
            return f"HK{candidate.zfill(5)}"

    if upper.startswith(('SH', 'SZ')) and not upper.startswith('SH.') and not upper.startswith('SZ.'):
        candidate = code[2:]
        if candidate.isdigit() and len(candidate) in (5, 6):
            return candidate

    if upper.startswith('BJ') and not upper.startswith('BJ.'):
        candidate = code[2:]
        if candidate.isdigit() and len(candidate) == 6:
            return candidate

    if '.' in code:
        base, suffix = code.rsplit('.', 1)
        if suffix.upper() == 'HK' and base.isdigit() and 1 <= len(base) <= 5:
            return f"HK{base.zfill(5)}"
        if suffix.upper() in ('SH', 'SZ', 'SS', 'BJ') and base.isdigit():
            return base

    return code


def _is_us_market(code: str) -> bool:
    """Return True for US stock/index codes (no Chinese exchange prefix)."""
    normalized = (code or "").strip().upper()
    return is_us_index_code(normalized) or is_us_stock_code(normalized)


def _is_hk_market(code: str) -> bool:
    """Return True for Hong Kong stock codes."""
    normalized = (code or "").strip().upper()
    if normalized.endswith(".HK"):
        base = normalized[:-3]
        return base.isdigit() and 1 <= len(base) <= 5
    if normalized.startswith("HK"):
        digits = normalized[2:]
        return digits.isdigit() and 1 <= len(digits) <= 5
    if normalized.isdigit() and len(normalized) == 5:
        return True
    return False


def is_etf_code(code: str) -> bool:
    """Return True for A-share ETF fund codes (conservative prefix rule)."""
    normalized = normalize_stock_code(code)
    return (
        normalized.isdigit()
        and len(normalized) == 6
        and normalized.startswith(ETF_PREFIXES)
    )


# Backward-compatible alias used across fetchers.
_is_etf_code = is_etf_code


def _market_tag(code: str) -> str:
    """Return market tag: cn / us / hk."""
    if _is_us_market(code):
        return "us"
    if _is_hk_market(code):
        return "hk"
    return "cn"


def is_bse_code(code: str) -> bool:
    """Return True for Beijing Stock Exchange (BSE) A-share codes."""
    c = (code or "").strip().split(".")[0]
    if len(c) != 6 or not c.isdigit():
        return False

    if c.startswith("900"):
        return False

    return c.startswith(("92", "43", "81", "82", "83", "87", "88"))


def is_st_stock(name: str) -> bool:
    """Return True when the stock name indicates ST/*ST status."""
    n = (name or "").upper()
    return 'ST' in n


def is_kc_cy_stock(code: str) -> bool:
    """Return True for STAR Market (688) or ChiNext (300) codes."""
    c = (code or "").strip().split(".")[0]
    return c.startswith("688") or c.startswith("30")


def canonical_stock_code(code: str) -> str:
    """Return the canonical uppercase form of a stock code."""
    return (code or "").strip().upper()


def is_hk_code(stock_code: str) -> bool:
    """Return True for Hong Kong stock codes (5-digit or HK-prefixed)."""
    code = stock_code.strip().lower()
    if code.endswith('.hk'):
        numeric_part = code[:-3]
        return numeric_part.isdigit() and 1 <= len(numeric_part) <= 5
    if code.startswith('hk'):
        numeric_part = code[2:]
        return numeric_part.isdigit() and 1 <= len(numeric_part) <= 5
    return code.isdigit() and len(code) == 5


# Backward-compatible aliases.
_is_hk_code = is_hk_code


def is_hk_stock_code(stock_code: str) -> bool:
    """Public API: determine if a stock code is a Hong Kong stock."""
    return is_hk_code(stock_code)


def is_us_code(stock_code: str) -> bool:
    """Return True for US stock codes (excluding US indices)."""
    return is_us_stock_code(stock_code)


# Backward-compatible alias.
_is_us_code = is_us_code


def to_sina_tx_symbol(stock_code: str) -> str:
    """Convert a 6-digit A-share code to sh/sz/bj prefixed symbol for Sina/Tencent APIs."""
    base = (stock_code.strip().split(".")[0] if "." in stock_code else stock_code).strip()
    if is_bse_code(base):
        return f"bj{base}"
    if base.startswith(("6", "5", "90")):
        return f"sh{base}"
    return f"sz{base}"


# Backward-compatible alias used by akshare_fetcher.
_to_sina_tx_symbol = to_sina_tx_symbol

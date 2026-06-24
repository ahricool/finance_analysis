# -*- coding: utf-8 -*-
"""A-share board classification and price-limit (涨跌停) rule resolution.

This is the single place that decides, for a given security, what its daily
price-limit regime is. Boards, risk-warning status and new-listing windows are
combined here so no other module has to re-derive A-share limit rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from finance_analysis.integrations.market_data.codes import (
    is_bse_code,
    is_etf_code,
    is_st_stock,
    normalize_stock_code,
)
from finance_analysis.integrations.market_data.realtime_types import (
    UnifiedRealtimeQuote,
    safe_float,
)

# Board labels surfaced to the rest of the task.
BOARD_MAIN = "main_board"
BOARD_CHINEXT = "chinext"
BOARD_STAR = "star_market"
BOARD_BSE = "bse"
BOARD_ST = "st_or_risk_warning"
BOARD_NEW_LISTING = "new_listing_unbounded"
BOARD_ETF = "etf"
BOARD_CONVERTIBLE_BOND = "convertible_bond"
BOARD_UNKNOWN = "unknown"

# Convertible-bond code prefixes (SH 110/111/113/118, SZ 12x/127/128/123).
_CONVERTIBLE_BOND_PREFIXES = ("110", "111", "113", "118", "120", "123", "127", "128")

# Daily price-limit ratios per structural board for ordinary trading.
_LIMIT_RATIO_MAIN = 0.10
_LIMIT_RATIO_ST = 0.05
_LIMIT_RATIO_GROWTH = 0.20  # ChiNext / STAR
_LIMIT_RATIO_BSE = 0.30

# STAR / ChiNext have no price limit during the first 5 trading days; we use a
# conservative calendar-day window because intraday data rarely carries the
# precise trading-day count.
_NEW_LISTING_UNBOUNDED_CALENDAR_DAYS = 8


@dataclass
class PriceLimitRule:
    """Resolved daily price-limit regime for one security."""

    limit_up_price: Optional[float]
    limit_down_price: Optional[float]
    limit_ratio: Optional[float]
    has_price_limit: bool
    board: str
    source: str
    warning: Optional[str] = None


def _structural_board(code: str) -> str:
    """Return the code-derived structural board, ignoring name/risk status."""
    if is_etf_code(code):
        return BOARD_ETF
    normalized = normalize_stock_code(code)
    base = normalized.split(".")[0]
    if not (base.isdigit() and len(base) == 6):
        return BOARD_UNKNOWN
    if base.startswith(_CONVERTIBLE_BOND_PREFIXES):
        return BOARD_CONVERTIBLE_BOND
    if is_bse_code(base):
        return BOARD_BSE
    if base.startswith("688"):
        return BOARD_STAR
    if base.startswith("30"):
        return BOARD_CHINEXT
    if base.startswith(("60", "00")):
        return BOARD_MAIN
    return BOARD_UNKNOWN


def is_risk_warning(name: str) -> bool:
    """Return whether the security name indicates ST / risk-warning status."""
    return is_st_stock(name)


def _is_new_listing_unbounded(board: str, listing_date: Optional[date], today: date) -> bool:
    """Heuristic for the no-price-limit window right after a new listing."""
    if listing_date is None:
        return False
    days_since = (today - listing_date).days
    if days_since < 0:
        return False
    if board in (BOARD_STAR, BOARD_CHINEXT):
        return days_since <= _NEW_LISTING_UNBOUNDED_CALENDAR_DAYS
    if board == BOARD_MAIN:
        # Main-board new stocks have no ±10% cap on the very first day.
        return days_since == 0
    return False


def classify_a_share_board(
    code: str,
    name: str = "",
    *,
    listing_date: Optional[date] = None,
    today: Optional[date] = None,
    security_type: str = "stock",
) -> str:
    """Classify a security into one of the task's board categories.

    ETF / convertible bond come straight from the code. New-listing-unbounded
    and risk-warning are overlays on the structural board.
    """
    if security_type == "etf":
        return BOARD_ETF
    structural = _structural_board(code)
    if structural in (BOARD_ETF, BOARD_CONVERTIBLE_BOND, BOARD_UNKNOWN):
        return structural

    today = today or date.today()
    if _is_new_listing_unbounded(structural, listing_date, today):
        return BOARD_NEW_LISTING
    if is_risk_warning(name):
        return BOARD_ST
    return structural


def _limit_ratio_for(structural: str, risk_warning: bool) -> Optional[float]:
    """Return the ordinary daily limit ratio combining board + risk warning."""
    if structural == BOARD_BSE:
        return _LIMIT_RATIO_BSE
    if structural in (BOARD_STAR, BOARD_CHINEXT):
        # Growth boards keep ±20% even for ST names.
        return _LIMIT_RATIO_GROWTH
    if structural == BOARD_MAIN:
        return _LIMIT_RATIO_ST if risk_warning else _LIMIT_RATIO_MAIN
    return None


def _round_price(value: Decimal) -> float:
    """Round a price to 2 decimals using banker-free half-up, like exchanges."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def resolve_price_limit_rule(
    *,
    code: str,
    name: str,
    pre_close: Optional[float],
    quote: Optional[UnifiedRealtimeQuote] = None,
    listing_date: Optional[date] = None,
    today: Optional[date] = None,
    security_type: str = "stock",
    explicit_limit_up: Optional[float] = None,
    explicit_limit_down: Optional[float] = None,
) -> PriceLimitRule:
    """Resolve the daily price-limit regime for a security.

    Priority:
      1. Exchange-provided limit-up / limit-down prices.
      2. Board + risk-warning + listing-date derived ratio.
      3. Unknown (never silently assume 10%).
    """
    board = classify_a_share_board(
        code,
        name,
        listing_date=listing_date,
        today=today,
        security_type=security_type,
    )
    structural = _structural_board(code)
    risk_warning = is_risk_warning(name)
    pre_close_val = safe_float(pre_close)

    # 1. Exchange-provided absolute limits win.
    explicit_up = safe_float(explicit_limit_up)
    explicit_down = safe_float(explicit_limit_down)
    if explicit_up is not None and explicit_up > 0 and explicit_down is not None and explicit_down > 0:
        ratio = None
        if pre_close_val and pre_close_val > 0:
            ratio = round((explicit_up - pre_close_val) / pre_close_val, 4)
        return PriceLimitRule(
            limit_up_price=round(explicit_up, 2),
            limit_down_price=round(explicit_down, 2),
            limit_ratio=ratio,
            has_price_limit=True,
            board=board,
            source="exchange",
        )

    # 2. Securities without a normal price limit.
    if board == BOARD_NEW_LISTING:
        return PriceLimitRule(
            limit_up_price=None,
            limit_down_price=None,
            limit_ratio=None,
            has_price_limit=False,
            board=board,
            source="new_listing",
            warning="新股上市初期无涨跌幅限制",
        )
    if board in (BOARD_ETF, BOARD_CONVERTIBLE_BOND, BOARD_UNKNOWN):
        return PriceLimitRule(
            limit_up_price=None,
            limit_down_price=None,
            limit_ratio=None,
            has_price_limit=False,
            board=board,
            source="board_rule",
            warning="该证券类型不适用普通股票涨跌停规则",
        )

    ratio = _limit_ratio_for(structural, risk_warning)
    if ratio is None or pre_close_val is None or pre_close_val <= 0:
        return PriceLimitRule(
            limit_up_price=None,
            limit_down_price=None,
            limit_ratio=ratio,
            has_price_limit=ratio is not None,
            board=board,
            source="unknown",
            warning="无法确定涨跌停价（缺少昨收或交易规则）",
        )

    pre_dec = Decimal(str(pre_close_val))
    ratio_dec = Decimal(str(ratio))
    limit_up = _round_price(pre_dec * (Decimal("1") + ratio_dec))
    limit_down = _round_price(pre_dec * (Decimal("1") - ratio_dec))
    return PriceLimitRule(
        limit_up_price=limit_up,
        limit_down_price=limit_down,
        limit_ratio=ratio,
        has_price_limit=True,
        board=board,
        source="board_rule",
    )

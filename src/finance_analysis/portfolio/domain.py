"""Pure portfolio-domain constants and value transformations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from finance_analysis.core.time import utc_now


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class FixedAccountDefinition:
    account_code: str
    name: str
    market: str
    currency: str


FIXED_ACCOUNTS = (
    FixedAccountDefinition("CN", "A股账户", "CN", "CNY"),
    FixedAccountDefinition("HK", "港股账户", "HK", "HKD"),
    FixedAccountDefinition("US", "美股账户", "US", "USD"),
)
FIXED_ACCOUNT_BY_CODE = {item.account_code: item for item in FIXED_ACCOUNTS}
CURRENCY_BY_MARKET = {item.market: item.currency for item in FIXED_ACCOUNTS}


def coerce_decimal(value: Decimal | int | str, *, field_name: str) -> Decimal:
    """Parse a finite Decimal without routing through binary floating point."""
    if isinstance(value, float):
        raise ValueError(f"{field_name} must be provided as a decimal string")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def decimal_to_string(value: Decimal) -> str:
    """Return a non-exponent Decimal string while preserving stored precision."""
    return format(value, "f")


def normalized_decimal_identity(value: Decimal | int | str) -> str:
    """Normalize equivalent Decimal spellings to one stable identity string."""
    parsed = coerce_decimal(value, field_name="decimal")
    if parsed == 0:
        return "0"
    normalized = format(parsed.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def build_option_canonical_symbol(
    underlying_canonical_symbol: str,
    expiration_date: date,
    option_type: str,
    strike_price: Decimal | int | str,
) -> str:
    """Build the stable internal identity for a standard US option contract."""
    underlying = str(underlying_canonical_symbol or "").strip().upper()
    kind = str(option_type or "").strip().upper()
    if kind not in {"CALL", "PUT"}:
        raise ValueError("option_type must be CALL or PUT")
    strike = coerce_decimal(strike_price, field_name="strike_price")
    if strike <= 0:
        raise ValueError("strike_price must be greater than 0")
    return f"{underlying}|{expiration_date.isoformat()}|{kind}|{normalized_decimal_identity(strike)}"


def current_us_market_date(now: datetime | None = None) -> date:
    """Return the current calendar date in the US market timezone."""
    current = now or utc_now()
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(NEW_YORK).date()


def option_days_to_expiration(expiration_date: date, now: datetime | None = None) -> int:
    """Calculate option DTE as natural calendar days in America/New_York."""
    return (expiration_date - current_us_market_date(now)).days

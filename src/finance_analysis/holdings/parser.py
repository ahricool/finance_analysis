# -*- coding: utf-8 -*-
"""Parse Accounts/Positions sheets by header name. Decimal money; timezone-explicit dates."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from finance_analysis.holdings.models import ParsedAccount, ParsedLeg, ParsedPosition  # pragma: allowlist secret
from finance_analysis.integrations.market_data.normalizer import canonical_symbol, infer_market  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import Market  # pragma: allowlist secret

ACCOUNT_REQUIRED = (
    "account_id",
    "account_name",
    "base_currency",
    "net_asset",
    "nav_as_of",
    "holdings_as_of",
    "positions_complete",
)
POSITION_REQUIRED = (
    "account_id",
    "position_id",
    "leg_id",
    "leg_role",
    "symbol",
    "asset_type",
    "quantity",
    "entry_price",
    "entry_time",
    "status",
)
COVERED_ASSET_TYPES = {"STOCK", "ETF"}
COVERED_MARKETS = {Market.CN, Market.US}
SHEETS_EPOCH = datetime(1899, 12, 30)


class SheetParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _header_map(row: Iterable[Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(row):
        name = str(cell or "").strip().lower()
        if not name:
            continue
        if name in mapping:
            raise SheetParseError("duplicate_header", f"duplicate column {name}")
        mapping[name] = index
    return mapping


def _cell(row: list[Any], headers: Mapping[str, int], name: str) -> Any:
    index = headers.get(name)
    if index is None or index >= len(row):
        return None
    return row[index]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_decimal(value: Any, *, field: str) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise SheetParseError("invalid_number", f"{field} is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise SheetParseError("invalid_number", f"{field} is not a number") from exc


def parse_bool(value: Any, *, field: str) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise SheetParseError("invalid_bool", f"{field} is not boolean")


def sheets_serial_to_datetime(value: float | int | Decimal, tz: ZoneInfo) -> datetime:
    days = Decimal(str(value))
    whole = int(days)
    fraction = days - whole
    base = SHEETS_EPOCH + timedelta(days=whole)
    microseconds = int(fraction * Decimal(24 * 60 * 60 * 1_000_000))
    naive = base + timedelta(microseconds=microseconds)
    return naive.replace(tzinfo=tz)


def parse_datetime(value: Any, *, field: str, tz: ZoneInfo) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz)
        return value
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return sheets_serial_to_datetime(value, tz)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SheetParseError("invalid_datetime", f"{field} is not an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed


def _coverage(symbol: str, asset_type: str, quantity: Decimal) -> tuple[str, str | None, str | None]:
    try:
        canonical = canonical_symbol(symbol)
        market = infer_market(canonical)
    except Exception:
        return "UNCOVERED_MARKET", None, "symbol_not_canonical"
    if market not in COVERED_MARKETS:
        return "UNCOVERED_MARKET", canonical, f"market_{market.value}"
    if str(asset_type).strip().upper() not in COVERED_ASSET_TYPES:
        return "UNCOVERED_ASSET", canonical, f"asset_{asset_type}"
    if quantity < 0:
        return "UNCOVERED_SIDE", canonical, "short_or_negative_quantity"
    return "COVERED", canonical, None


def parse_accounts(rows: list[list[Any]], *, tz: ZoneInfo) -> list[ParsedAccount]:
    if not rows:
        raise SheetParseError("missing_accounts_header", "Accounts 缺少表头")
    headers = _header_map(rows[0])
    missing = [name for name in ACCOUNT_REQUIRED if name not in headers]
    if missing:
        raise SheetParseError("missing_accounts_header", f"Accounts 缺少列: {', '.join(missing)}")
    accounts: list[ParsedAccount] = []
    seen: set[str] = set()
    for row in rows[1:]:
        if not any(str(cell).strip() for cell in row if cell is not None):
            continue
        account_id = _text(_cell(row, headers, "account_id"))
        if not account_id:
            raise SheetParseError("invalid_account", "account_id 不能为空")
        if account_id in seen:
            raise SheetParseError("duplicate_account", f"重复 account_id {account_id}")
        seen.add(account_id)
        extras = {
            name: _cell(row, headers, name)
            for name in headers
            if name not in ACCOUNT_REQUIRED and name != "cash"
        }
        accounts.append(
            ParsedAccount(
                account_id=account_id,
                account_name=_text(_cell(row, headers, "account_name")) or account_id,
                base_currency=(_text(_cell(row, headers, "base_currency")) or "").upper(),
                net_asset=parse_decimal(_cell(row, headers, "net_asset"), field="net_asset"),
                nav_as_of=parse_datetime(_cell(row, headers, "nav_as_of"), field="nav_as_of", tz=tz),
                holdings_as_of=parse_datetime(
                    _cell(row, headers, "holdings_as_of"), field="holdings_as_of", tz=tz
                ),
                positions_complete=bool(parse_bool(_cell(row, headers, "positions_complete"), field="positions_complete")),
                cash=parse_decimal(_cell(row, headers, "cash"), field="cash"),
                extras=extras,
            )
        )
    return accounts


def parse_legs(rows: list[list[Any]], *, tz: ZoneInfo) -> list[ParsedLeg]:
    if not rows:
        raise SheetParseError("missing_positions_header", "Positions 缺少表头")
    headers = _header_map(rows[0])
    missing = [name for name in POSITION_REQUIRED if name not in headers]
    if missing:
        raise SheetParseError("missing_positions_header", f"Positions 缺少列: {', '.join(missing)}")
    legs: list[ParsedLeg] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows[1:]:
        if not any(str(cell).strip() for cell in row if cell is not None):
            continue
        account_id = _text(_cell(row, headers, "account_id"))
        position_id = _text(_cell(row, headers, "position_id"))
        leg_id = _text(_cell(row, headers, "leg_id"))
        if not account_id or not position_id or not leg_id:
            raise SheetParseError("invalid_leg_id", "account_id/position_id/leg_id 不能为空")
        key = (account_id, position_id, leg_id)
        if key in seen:
            raise SheetParseError("duplicate_leg", f"重复复合 ID {account_id}/{position_id}/{leg_id}")
        seen.add(key)
        quantity = parse_decimal(_cell(row, headers, "quantity"), field="quantity")
        entry_price = parse_decimal(_cell(row, headers, "entry_price"), field="entry_price")
        if quantity is None or entry_price is None:
            raise SheetParseError("invalid_number", "quantity/entry_price 不能为空")
        role = (_text(_cell(row, headers, "leg_role")) or "").upper()
        status = (_text(_cell(row, headers, "status")) or "").upper()
        if role not in {"CORE", "ADDON"}:
            raise SheetParseError("invalid_leg_role", f"非法 leg_role {role}")
        if status not in {"OPEN", "CLOSED"}:
            raise SheetParseError("invalid_status", f"非法 status {status}")
        if status == "CLOSED" and quantity != 0:
            raise SheetParseError("closed_quantity", "CLOSED 腿数量必须为 0")
        if status == "OPEN":
            if quantity <= 0:
                raise SheetParseError("open_quantity", "OPEN 腿数量必须为正")
            if entry_price <= 0:
                raise SheetParseError("open_entry_price", "OPEN 支持资产需要有限正入场价")
        symbol = _text(_cell(row, headers, "symbol")) or ""
        asset_type = (_text(_cell(row, headers, "asset_type")) or "").upper()
        coverage, canonical, reason = _coverage(symbol, asset_type, quantity)
        known = set(POSITION_REQUIRED) | {
            "currency",
            "initial_stop",
            "available_quantity",
            "available_as_of",
            "risk_group",
            "manual_market_value",
            "valuation_as_of",
        }
        extras = {name: _cell(row, headers, name) for name in headers if name not in known}
        entry_time = parse_datetime(_cell(row, headers, "entry_time"), field="entry_time", tz=tz)
        if entry_time is None:
            raise SheetParseError("invalid_datetime", "entry_time 不能为空")
        legs.append(
            ParsedLeg(
                account_id=account_id,
                position_id=position_id,
                leg_id=leg_id,
                leg_role=role,
                symbol=symbol,
                canonical_symbol=canonical,
                asset_type=asset_type,
                quantity=quantity,
                entry_price=entry_price,
                entry_time=entry_time,
                status=status,
                currency=_text(_cell(row, headers, "currency")),
                initial_stop=parse_decimal(_cell(row, headers, "initial_stop"), field="initial_stop"),
                available_quantity=parse_decimal(
                    _cell(row, headers, "available_quantity"), field="available_quantity"
                ),
                available_as_of=parse_datetime(
                    _cell(row, headers, "available_as_of"), field="available_as_of", tz=tz
                ),
                risk_group=_text(_cell(row, headers, "risk_group")),
                manual_market_value=parse_decimal(
                    _cell(row, headers, "manual_market_value"), field="manual_market_value"
                ),
                valuation_as_of=parse_datetime(
                    _cell(row, headers, "valuation_as_of"), field="valuation_as_of", tz=tz
                ),
                extras=extras,
                coverage=coverage,
                coverage_reason=reason,
            )
        )
    return legs


def group_positions(legs: list[ParsedLeg]) -> list[ParsedPosition]:
    grouped: dict[tuple[str, str], list[ParsedLeg]] = {}
    for leg in legs:
        grouped.setdefault((leg.account_id, leg.position_id), []).append(leg)
    positions: list[ParsedPosition] = []
    for (account_id, position_id), items in grouped.items():
        symbols = {item.canonical_symbol or item.symbol for item in items}
        accounts = {item.account_id for item in items}
        if len(accounts) != 1 or len(symbols) != 1:
            raise SheetParseError("position_identity", f"{account_id}/{position_id} 必须同账户同证券")
        cores = [item for item in items if item.leg_role == "CORE"]
        if len(cores) != 1:
            raise SheetParseError("core_count", f"{account_id}/{position_id} 必须恰好一条 CORE")
        sample = items[0]
        positions.append(
            ParsedPosition(
                account_id=account_id,
                position_id=position_id,
                symbol=sample.symbol,
                canonical_symbol=sample.canonical_symbol,
                asset_type=sample.asset_type,
                currency=sample.currency,
                legs=sorted(items, key=lambda item: (item.entry_time, item.leg_id)),
            )
        )
    return sorted(positions, key=lambda item: (item.account_id, item.position_id))

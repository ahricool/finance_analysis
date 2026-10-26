"""Validate the full Fuyao Dragon Tiger contract without the legacy symbol-only cache."""

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import math
import unicodedata

MONEY_FIELDS = (
    "net_value",
    "buy_value",
    "sell_value",
    "org_net_value",
    "hot_money_net_value",
    "hot_money_item_net_value",
)
OBSERVATION_PERIODS = (1, 3)
# Extended abnormal-movement boards are valid upstream records, but not inputs
# to the 1-day cumulative / 3-day cross-sectional research views.
AUDIT_ONLY_PERIODS = (10, 30)


def amount(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid Dragon Tiger amount")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid Dragon Tiger amount") from None
    if not number.is_finite() or abs(number) > Decimal("1e16"):
        raise ValueError("Invalid Dragon Tiger amount")
    return str(number.quantize(Decimal("0.01")))


def source_rows(data, board):
    """Read raw records without inventing identities for absent thscode values."""
    if not isinstance(data, dict):
        raise ValueError("Invalid Dragon Tiger response")
    stocks, groups = data.get("stock_items"), data.get("hot_money_items")
    if not isinstance(stocks, list) or not isinstance(groups, list):
        raise ValueError("Invalid Dragon Tiger rows")
    if (board == "hot_money" and stocks) or (board != "hot_money" and groups):
        raise ValueError("Unexpected Dragon Tiger board structure")
    if board != "hot_money":
        rows = stocks
    else:
        rows = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("name"), str) or not group["name"].strip():
                raise ValueError("Invalid Dragon Tiger hot-money group")
            if not isinstance(group.get("rows"), list):
                raise ValueError("Invalid Dragon Tiger hot-money rows")
            rows.extend(group["rows"])
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Invalid Dragon Tiger row")
    return rows


def source_identity(row):
    # Upstream stock_count counts raw ticker identities, including instruments
    # without a resolved thscode. This identity is ONLY for count validation.
    ticker = row.get("ticker")
    if isinstance(ticker, str) and re.fullmatch(r"\d{6}", ticker):
        return ticker
    symbol = row.get("thscode")
    if isinstance(symbol, str) and re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol):
        return symbol.split(".")[0]
    return None


def is_bond_code(symbol):
    # CN 11/12 bond-code families must not enter equity research even if a
    # mistaken security-master row classifies the instrument as a stock.
    return isinstance(symbol, str) and bool(re.fullmatch(r"1[12]\d{4}\.(SH|SZ|BJ)", symbol))


def normalize_row(row):
    if not isinstance(row, dict) or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(row.get("thscode", ""))):
        raise ValueError("Invalid Dragon Tiger stock code")
    ticker = row.get("ticker")
    if isinstance(ticker, str) and re.fullmatch(r"\d{6}", ticker) and ticker != row["thscode"].split(".")[0]:
        raise ValueError("Dragon Tiger ticker/code mismatch")
    if type(row.get("range_days")) is not int or row["range_days"] not in OBSERVATION_PERIODS + AUDIT_ONLY_PERIODS:
        raise ValueError("Invalid Dragon Tiger period")
    concepts = row.get("concept_list") or []
    if not isinstance(concepts, list) or any(
        not isinstance(c, dict) or not isinstance(c.get("name"), str) for c in concepts
    ):
        raise ValueError("Invalid Dragon Tiger concepts")
    names = sorted({unicodedata.normalize("NFKC", c["name"]).strip() for c in concepts} - {""})
    return {
        "symbol": row["thscode"],
        "name": str(row.get("name") or row["thscode"]),
        "range_days": row["range_days"],
        "concepts": names,
        **{field: amount(row.get(field)) for field in MONEY_FIELDS},
    }


def normalize_source(data, day: date, board: str, *, allowed_symbols=None):
    if not isinstance(data, dict) or data.get("trade_date") != day.isoformat() or data.get("board_type") != board:
        raise ValueError("Dragon Tiger response date/board mismatch")
    for key in ("count", "stock_count"):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ValueError("Invalid Dragon Tiger count")
    raw_rows = source_rows(data, board)
    stocks, groups = data["stock_items"], data["hot_money_items"]
    discarded = {"missing_thscode": 0, "bond": 0, "not_in_instrument": 0}

    def keep(raw):
        symbol = raw.get("thscode")
        if symbol is None or (isinstance(symbol, str) and not symbol.strip()):
            discarded["missing_thscode"] += 1
            return False
        if is_bond_code(symbol):
            discarded["bond"] += 1
            return False
        if allowed_symbols is not None and (not isinstance(symbol, str) or symbol not in allowed_symbols):
            discarded["not_in_instrument"] += 1
            return False
        return True

    rows, details, duplicates = {}, {}, 0
    if board != "hot_money":
        identities = [source_identity(raw) for raw in stocks]
        known = {identity for identity in identities if identity is not None}
        unknown = identities.count(None)
        if (
            len(stocks) != data["count"]
            or not max(len(known), bool(stocks)) <= data["stock_count"] <= len(known) + unknown
        ):
            raise ValueError("Incomplete Dragon Tiger stock board")
        for raw in stocks:
            if not keep(raw):
                continue
            row = normalize_row(raw)
            key = (row["symbol"], row["range_days"])
            if key in rows:
                if rows[key] != row:
                    raise ValueError("Conflicting Dragon Tiger stock records")
                duplicates += 1
            rows[key] = row
    else:
        # count/stock_count describe the upstream stock board, NOT the limited hot-money groups.
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("name"), str) or not group["name"].strip():
                raise ValueError("Invalid Dragon Tiger hot-money group")
            if not isinstance(group.get("rows"), list):
                raise ValueError("Invalid Dragon Tiger hot-money rows")
            for raw in group["rows"]:
                if not keep(raw):
                    continue
                row = normalize_row(raw)
                row["hot_money_name"] = group["name"].strip()
                key = (row["hot_money_name"], row["symbol"], row["range_days"])
                if key in details:
                    if details[key] != row:
                        raise ValueError("Conflicting Dragon Tiger hot-money details")
                    duplicates += 1
                details[key] = row
    timestamp = data.get("timestamp")
    if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or not math.isfinite(timestamp):
        raise ValueError("Invalid Dragon Tiger source timestamp")
    # Partition retained instruments after raw count and retained-field checks.
    # Extended-period evidence stays separate from 1/3-day observations.
    excluded_rows = [r for r in rows.values() if r["range_days"] in AUDIT_ONLY_PERIODS]
    excluded_details = [r for r in details.values() if r["range_days"] in AUDIT_ONLY_PERIODS]
    excluded = excluded_details if board == "hot_money" else excluded_rows
    return deepcopy(
        {
            "board": board,
            "trade_date": day.isoformat(),
            "source_timestamp_ms": timestamp,
            "upstream_count": data["count"],
            "upstream_stock_count": data["stock_count"],
            "rows": [r for r in rows.values() if r["range_days"] in OBSERVATION_PERIODS],
            "details": [r for r in details.values() if r["range_days"] in OBSERVATION_PERIODS],
            "excluded_rows": excluded_rows,
            "excluded_details": excluded_details,
            "quality": {
                "input_row_count": len(raw_rows),
                "discarded_counts": discarded,
                "retained_row_count": len(raw_rows) - sum(discarded.values()),
                "unresolved_source_identity_count": unknown if board != "hot_money" else None,
                "instrument_scope": "current_instrument" if allowed_symbols is not None else "unfiltered",
                "duplicates_removed": duplicates,
                "conflicts": 0,
                "detail_scope": "limited_named_groups" if board == "hot_money" else "stock_board",
                "excluded_period_counts": {
                    str(period): sum(r["range_days"] == period for r in excluded) for period in AUDIT_ONLY_PERIODS
                },
            },
        }
    )

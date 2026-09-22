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


def normalize_row(row):
    if not isinstance(row, dict) or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(row.get("thscode", ""))):
        raise ValueError("Invalid Dragon Tiger stock code")
    if type(row.get("range_days")) is not int or row["range_days"] not in (1, 3):
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


def normalize_source(data, day: date, board: str):
    if not isinstance(data, dict) or data.get("trade_date") != day.isoformat() or data.get("board_type") != board:
        raise ValueError("Dragon Tiger response date/board mismatch")
    for key in ("count", "stock_count"):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ValueError("Invalid Dragon Tiger count")
    stocks, groups = data.get("stock_items"), data.get("hot_money_items")
    if not isinstance(stocks, list) or not isinstance(groups, list):
        raise ValueError("Invalid Dragon Tiger rows")
    if (board == "hot_money" and stocks) or (board != "hot_money" and groups):
        raise ValueError("Unexpected Dragon Tiger board structure")
    rows, details, duplicates = {}, {}, 0
    if board != "hot_money":
        if (
            len(stocks) != data["count"]
            or len({r.get("thscode") for r in stocks if isinstance(r, dict)}) != data["stock_count"]
        ):
            raise ValueError("Incomplete Dragon Tiger stock board")
        for raw in stocks:
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
    return deepcopy(
        {
            "board": board,
            "trade_date": day.isoformat(),
            "source_timestamp_ms": timestamp,
            "upstream_count": data["count"],
            "upstream_stock_count": data["stock_count"],
            "rows": list(rows.values()),
            "details": list(details.values()),
            "quality": {
                "duplicates_removed": duplicates,
                "conflicts": 0,
                "detail_scope": "limited_named_groups" if board == "hot_money" else "stock_board",
            },
        }
    )

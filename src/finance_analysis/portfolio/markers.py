# -*- coding: utf-8 -*-
"""Daily BST markers from trade_operation. No dedicated BST table."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from finance_analysis.core.time import coerce_aware_utc  # pragma: allowlist secret
from finance_analysis.integrations.market_data.normalizer import MARKET_TIMEZONES  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import Market  # pragma: allowlist secret
from finance_analysis.portfolio.models import TradeMarker, TradeMarkerOperation  # pragma: allowlist secret


def _local_date(value: datetime, market: str):
    aware = coerce_aware_utc(value) or value
    zone = MARKET_TIMEZONES.get(Market(market) if market in {"CN", "US", "HK"} else Market.US)
    if zone is None:
        return aware.date(), aware
    local = aware.astimezone(zone)
    return local.date(), local


def markers_from_operations(operations, *, market: str) -> list[TradeMarker]:
    grouped: dict = defaultdict(list)
    for row in operations:
        side = getattr(row, "side", None) or row.get("side")
        if side not in {"BUY", "SELL"}:
            continue
        executed = getattr(row, "executed_at", None) or row.get("executed_at")
        quantity = getattr(row, "quantity", None) if not isinstance(row, dict) else row.get("quantity")
        price = getattr(row, "price", None) if not isinstance(row, dict) else row.get("price")
        note = getattr(row, "note", None) if not isinstance(row, dict) else row.get("note")
        day, local = _local_date(executed, market)
        grouped[day].append(
            TradeMarkerOperation(
                executed_at=local,
                side=side,
                quantity=Decimal(str(quantity)),
                price=Decimal(str(price)),
                note=note,
            )
        )
    markers: list[TradeMarker] = []
    for day, items in sorted(grouped.items()):
        sides = {item.side for item in items}
        if sides == {"BUY"}:
            kind = "B"
        elif sides == {"SELL"}:
            kind = "S"
        else:
            kind = "T"
        markers.append(
            TradeMarker(
                timestamp=datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
                type=kind,
                operations=tuple(sorted(items, key=lambda item: item.executed_at)),
            )
        )
    return markers

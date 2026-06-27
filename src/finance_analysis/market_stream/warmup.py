"""Historical 1-minute bar loading and deterministic realtime merge rules."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.integrations.market_data.realtime_state.models import CandleState


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


class LongbridgeHistoryLoader:
    def __init__(self, fetcher: LongbridgeFetcher | None = None) -> None:
        self.fetcher = fetcher or LongbridgeFetcher()

    async def fetch(self, symbol: str, count: int) -> list[CandleState]:
        raw = await asyncio.to_thread(
            self.fetcher.get_minute_candlesticks,
            symbol,
            1,
            count,
            False,
        )
        received_at = datetime.now(timezone.utc)
        current_minute = received_at.replace(second=0, microsecond=0)
        bars: list[CandleState] = []
        for item in raw:
            try:
                bar_time = _parse_time(item.get("bar_time") or item.get("timestamp"))
                bar = CandleState(
                    symbol=symbol,
                    bar_time=bar_time,
                    open=Decimal(str(item["open"])),
                    high=Decimal(str(item["high"])),
                    low=Decimal(str(item["low"])),
                    close=Decimal(str(item["close"])),
                    volume=int(item.get("volume") or 0),
                    turnover=Decimal(str(item["turnover"])) if item.get("turnover") is not None else None,
                    trade_session=str(item.get("trade_session") or "") or None,
                    confirmed=bar_time < current_minute,
                    received_at=received_at,
                )
                if bar.is_valid():
                    bars.append(bar)
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        if not bars:
            return []
        market_tz = ZoneInfo("America/New_York")
        latest_session = max(bar.bar_time.astimezone(market_tz).date() for bar in bars)
        return [bar for bar in bars if bar.bar_time.astimezone(market_tz).date() == latest_session]


def merge_warmup_bars(
    historical: Iterable[CandleState],
    realtime: Iterable[CandleState],
    *,
    limit: int,
) -> list[CandleState]:
    """Merge by minute/session while preserving confirmed history and live current bars."""
    history = [bar for bar in historical if bar.is_valid()]
    live = [bar for bar in realtime if bar.is_valid()]
    all_bars = history + live
    if not all_bars:
        return []
    newest_identity = max(bar.identity for bar in all_bars)
    grouped: dict[tuple[datetime, str], list[tuple[bool, CandleState]]] = defaultdict(list)
    for bar in history:
        grouped[bar.identity].append((False, bar))
    for bar in live:
        grouped[bar.identity].append((True, bar))

    merged: list[CandleState] = []
    for identity, candidates in grouped.items():
        live_candidates = [bar for is_live, bar in candidates if is_live]
        if identity == newest_identity and live_candidates:
            selected = max(live_candidates, key=lambda item: item.received_at)
        else:
            selected = max(
                (bar for _, bar in candidates),
                key=lambda item: (item.confirmed, item.received_at),
            )
        merged.append(selected)
    merged.sort(key=lambda item: (item.bar_time, item.trade_session or ""))
    return merged[-max(1, limit) :]

"""Historical 1-minute bar loading and deterministic realtime merge rules."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from finance_analysis.integrations.market_data.providers.longbridge.normalizer import longbridge_datetime_to_utc
from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.market_stream.config import latest_completed_bar_time, market_trading_date
from finance_analysis.stocks.markets import MarketType


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return longbridge_datetime_to_utc(value, datetime.fromtimestamp(value.timestamp(), tz=timezone.utc))

    text = str(value).strip()
    if not text:
        raise ValueError("empty timestamp")

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return longbridge_datetime_to_utc(float(text), datetime.fromtimestamp(float(text), tz=timezone.utc))

    return longbridge_datetime_to_utc(parsed, datetime.fromtimestamp(parsed.timestamp(), tz=timezone.utc))


class LongbridgeHistoryLoader:
    def __init__(self, fetcher: LongbridgeFetcher | None = None) -> None:
        self.fetcher = fetcher or LongbridgeFetcher()

    async def fetch(self, symbol: str, market_type: MarketType, count: int) -> list[CandleState]:
        raw = await asyncio.to_thread(
            self.fetcher.get_minute_candlesticks,
            symbol,
            1,
            count,
            False,
        )
        received_at = datetime.now(timezone.utc)
        expected_completed = latest_completed_bar_time(received_at, market_type)
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
                    confirmed=expected_completed is not None and bar_time <= expected_completed,
                    received_at=received_at,
                )
                if bar.is_valid():
                    bars.append(bar)
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        if not bars:
            return []
        latest_session = max(market_trading_date(bar.bar_time, market_type) for bar in bars)
        return [bar for bar in bars if market_trading_date(bar.bar_time, market_type) == latest_session]


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

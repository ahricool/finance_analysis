"""Convert Longbridge SDK push objects into provider-independent events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from finance_analysis.integrations.market_data.realtime_state.models import CandleState


def longbridge_datetime_to_utc(value: Any, fallback: datetime) -> datetime:
    if value is None:
        return fallback

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc)

        # Longbridge SDK's naive datetime represents the system local time.
        return datetime.fromtimestamp(value.timestamp(), tz=timezone.utc)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return fallback
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.fromtimestamp(float(text), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                return fallback
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
        return datetime.fromtimestamp(parsed.timestamp(), tz=timezone.utc)

    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return fallback


def _time(value: Any, fallback: datetime) -> datetime:
    return longbridge_datetime_to_utc(value, fallback)


def _session(value: Any) -> str | None:
    if value is None:
        return None
    text = getattr(value, "name", None) or str(value)
    return text or None


@dataclass(slots=True)
class MarketEvent:
    event_type: str
    symbol: str
    event_time: datetime
    received_at: datetime
    sequence: int | None
    trade_session: str | None
    payload: dict[str, Any]
    connection_generation: int


def normalize_quote(symbol: str, push: Any, *, generation: int) -> MarketEvent:
    received_at = datetime.now(timezone.utc)
    event_time = _time(getattr(push, "timestamp", None), received_at)
    payload: dict[str, Any] = {}
    for source, target in (
        ("last_done", "last_price"),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("volume", "volume"),
        ("turnover", "turnover"),
        ("sequence", "sequence"),
    ):
        value = getattr(push, source, None)
        if value is not None:
            payload[target] = value
    trade_session = _session(getattr(push, "trade_session", None))
    payload["trade_session"] = trade_session
    return MarketEvent(
        event_type="quote",
        symbol=symbol,
        event_time=event_time,
        received_at=received_at,
        sequence=payload.get("sequence"),
        trade_session=trade_session,
        payload=payload,
        connection_generation=generation,
    )


def normalize_candlestick(symbol: str, push: Any, *, generation: int) -> MarketEvent:
    received_at = datetime.now(timezone.utc)
    candle = getattr(push, "candlestick", push)
    event_time = _time(getattr(candle, "timestamp", None), received_at)
    trade_session = _session(getattr(candle, "trade_session", None))
    payload = {
        "bar_time": event_time,
        "open": getattr(candle, "open", None),
        "high": getattr(candle, "high", None),
        "low": getattr(candle, "low", None),
        "close": getattr(candle, "close", None),
        "volume": getattr(candle, "volume", 0),
        "turnover": getattr(candle, "turnover", None),
        "trade_session": trade_session,
        "confirmed": bool(getattr(push, "is_confirmed", False)),
    }
    return MarketEvent(
        event_type="candle_1m",
        symbol=symbol,
        event_time=event_time,
        received_at=received_at,
        sequence=None,
        trade_session=trade_session,
        payload=payload,
        connection_generation=generation,
    )


def event_to_candle(event: MarketEvent) -> CandleState:
    payload = event.payload
    return CandleState(
        symbol=event.symbol,
        bar_time=payload["bar_time"],
        open=Decimal(str(payload["open"])),
        high=Decimal(str(payload["high"])),
        low=Decimal(str(payload["low"])),
        close=Decimal(str(payload["close"])),
        volume=int(payload.get("volume") or 0),
        turnover=Decimal(str(payload["turnover"])) if payload.get("turnover") is not None else None,
        trade_session=payload.get("trade_session"),
        confirmed=bool(payload.get("confirmed")),
        received_at=event.received_at,
    )

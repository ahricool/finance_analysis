"""Serializable realtime quote and candlestick state."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Mapping, cast

TrendDirection = Literal["above", "below", "neutral", "insufficient"]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass(slots=True)
class QuoteState:
    symbol: str
    last_price: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    pre_close: Decimal | None = None
    volume: int | None = None
    turnover: Decimal | None = None
    sequence: int | None = None
    trade_session: str | None = None
    event_time: datetime | None = None
    received_at: datetime | None = None

    def merge(self, payload: Mapping[str, Any], *, event_time: datetime, received_at: datetime) -> bool:
        """Merge a partial push; stale sequence values cannot replace newer state."""
        incoming_sequence = payload.get("sequence")
        if incoming_sequence is not None:
            incoming_sequence = int(incoming_sequence)
            if self.sequence is not None and incoming_sequence < self.sequence:
                return False

        decimal_fields = {"last_price", "open", "high", "low", "pre_close", "turnover"}
        int_fields = {"volume", "sequence"}
        for field in fields(self):
            name = field.name
            if name not in payload or payload[name] is None:
                continue
            value = payload[name]
            if name in decimal_fields:
                value = _decimal(value)
            elif name in int_fields:
                value = int(value)
            setattr(self, name, value)
        self.event_time = event_time
        self.received_at = received_at
        return True


@dataclass(slots=True)
class CandleState:
    symbol: str
    bar_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal | None
    trade_session: str | None
    confirmed: bool
    received_at: datetime

    @property
    def identity(self) -> tuple[datetime, str]:
        return self.bar_time, self.trade_session or ""

    def is_valid(self) -> bool:
        return (
            self.open > 0
            and self.high > 0
            and self.low > 0
            and self.close > 0
            and self.high >= max(self.open, self.close, self.low)
            and self.low <= min(self.open, self.close, self.high)
            and self.volume >= 0
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CandleState":
        bar_time = _datetime(value.get("bar_time") or value.get("timestamp"))
        received_at = _datetime(value.get("received_at")) or bar_time
        if bar_time is None or received_at is None:
            raise ValueError("candlestick requires bar_time and received_at")
        return cls(
            symbol=str(value["symbol"]),
            bar_time=bar_time,
            open=_decimal(value["open"]),  # type: ignore[arg-type]
            high=_decimal(value["high"]),  # type: ignore[arg-type]
            low=_decimal(value["low"]),  # type: ignore[arg-type]
            close=_decimal(value["close"]),  # type: ignore[arg-type]
            volume=int(value.get("volume") or 0),
            turnover=_decimal(value.get("turnover")),
            trade_session=str(value.get("trade_session") or "") or None,
            confirmed=str(value.get("confirmed", "1")).lower() in {"1", "true", "yes"},
            received_at=received_at,
        )


@dataclass(slots=True)
class TrendState:
    symbol: str
    timeframe: Literal["1m"] = "1m"
    target_period: int = 20
    effective_period: int = 0
    minimum_period: int = 5
    state: TrendDirection = "insufficient"
    streak: int = 0
    ma_value: Decimal | None = None
    close: Decimal | None = None
    distance_pct: Decimal | None = None
    bar_time: datetime | None = None
    trading_date: date | None = None
    trade_session: str | None = None
    confirmed: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrendState":
        trading_date = value.get("trading_date")
        state = str(value.get("state") or "insufficient")
        if state not in {"above", "below", "neutral", "insufficient"}:
            state = "insufficient"
        return cls(
            symbol=str(value["symbol"]),
            timeframe="1m",
            target_period=int(value.get("target_period") or 20),
            effective_period=int(value.get("effective_period") or 0),
            minimum_period=int(value.get("minimum_period") or 5),
            state=cast(TrendDirection, state),
            streak=int(value.get("streak") or 0),
            ma_value=_decimal(value.get("ma_value")),
            close=_decimal(value.get("close")),
            distance_pct=_decimal(value.get("distance_pct")),
            bar_time=_datetime(value.get("bar_time")),
            trading_date=(
                (trading_date if isinstance(trading_date, date) else date.fromisoformat(str(trading_date)))
                if trading_date
                else None
            ),
            trade_session=str(value.get("trade_session") or "") or None,
            confirmed=str(value.get("confirmed", "0")).lower() in {"1", "true", "yes"},
        )

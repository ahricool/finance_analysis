"""Typed signal and Redis state models for realtime price-action patterns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Mapping, cast

PatternType = Literal[
    "failed_breakout_reclaim",
    "breakout_retest_continuation",
    "micro_double_bottom_top",
    "impulse_pullback_resume",
    "compression_expansion",
    "vwap_reclaim_breakdown",
]
PatternDirection = Literal[
    "bullish_continuation",
    "bearish_continuation",
    "bearish_to_bullish",
    "bullish_to_bearish",
    "bullish_breakout",
    "bearish_breakout",
    "neutral_wait",
]
PatternStage = Literal["forming", "warning", "confirmed"]
PatternStateStatus = Literal["insufficient", "none", "active"]


def _datetime(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _date(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True, slots=True)
class PatternSignal:
    symbol: str
    pattern_type: PatternType
    pattern_name: str
    direction: PatternDirection
    stage: PatternStage
    quality_score: int
    occurred_at: datetime
    confirmed_at: datetime | None
    trading_date: date | None
    trade_session: str | None
    bars_ago: int
    session_minutes_ago: int
    reference_level: Decimal | None
    invalidation_price: Decimal | None
    reasons: tuple[str, ...]
    confirmed: bool
    timeframe: Literal["1m"] = "1m"

    def __post_init__(self) -> None:
        if not 0 <= self.quality_score <= 100:
            raise ValueError("quality_score must be between 0 and 100")
        if self.bars_ago < 0 or self.session_minutes_ago < 0:
            raise ValueError("pattern age cannot be negative")
        if self.confirmed != (self.stage == "confirmed"):
            raise ValueError("confirmed must match the confirmed stage")

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "pattern_type": self.pattern_type,
            "pattern_name": self.pattern_name,
            "direction": self.direction,
            "stage": self.stage,
            "quality_score": self.quality_score,
            "occurred_at": self.occurred_at.isoformat(),
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "trading_date": self.trading_date.isoformat() if self.trading_date else None,
            "trade_session": self.trade_session,
            "bars_ago": self.bars_ago,
            "session_minutes_ago": self.session_minutes_ago,
            "reference_level": str(self.reference_level) if self.reference_level is not None else None,
            "invalidation_price": str(self.invalidation_price) if self.invalidation_price is not None else None,
            "reasons": list(self.reasons),
            "confirmed": self.confirmed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatternSignal":
        occurred_at = _datetime(value.get("occurred_at"))
        if occurred_at is None:
            raise ValueError("pattern signal requires occurred_at")
        return cls(
            symbol=str(value["symbol"]),
            timeframe="1m",
            pattern_type=cast(PatternType, value["pattern_type"]),
            pattern_name=str(value["pattern_name"]),
            direction=cast(PatternDirection, value["direction"]),
            stage=cast(PatternStage, value["stage"]),
            quality_score=int(value["quality_score"]),
            occurred_at=occurred_at,
            confirmed_at=_datetime(value.get("confirmed_at")),
            trading_date=_date(value.get("trading_date")),
            trade_session=str(value.get("trade_session") or "") or None,
            bars_ago=int(value.get("bars_ago") or 0),
            session_minutes_ago=int(value.get("session_minutes_ago") or 0),
            reference_level=_decimal(value.get("reference_level")),
            invalidation_price=_decimal(value.get("invalidation_price")),
            reasons=tuple(str(item) for item in value.get("reasons") or ()),
            confirmed=str(value.get("confirmed", "0")).lower() in {"1", "true", "yes"},
        )


@dataclass(frozen=True, slots=True)
class PatternState:
    symbol: str
    status: PatternStateStatus = "insufficient"
    signal: PatternSignal | None = None
    trading_date: date | None = None
    bar_time: datetime | None = None
    timeframe: Literal["1m"] = "1m"

    def __post_init__(self) -> None:
        if (self.status == "active") != (self.signal is not None):
            raise ValueError("active pattern state must contain exactly one signal")

    def to_mapping(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "signal": (
                json.dumps(self.signal.to_dict(), ensure_ascii=False, separators=(",", ":")) if self.signal else ""
            ),
            "trading_date": self.trading_date.isoformat() if self.trading_date else "",
            "bar_time": self.bar_time.isoformat() if self.bar_time else "",
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PatternState":
        status = str(value.get("status") or "insufficient")
        if status not in {"insufficient", "none", "active"}:
            status = "insufficient"
        raw_signal = value.get("signal")
        signal = PatternSignal.from_dict(json.loads(str(raw_signal))) if raw_signal else None
        if status == "active" and signal is None:
            status = "insufficient"
        if status != "active":
            signal = None
        return cls(
            symbol=str(value["symbol"]),
            timeframe="1m",
            status=cast(PatternStateStatus, status),
            signal=signal,
            trading_date=_date(value.get("trading_date")),
            bar_time=_datetime(value.get("bar_time")),
        )

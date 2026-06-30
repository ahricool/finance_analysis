"""Incremental forward-return evaluation for persisted market signals."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, Sequence
from zoneinfo import ZoneInfo

from finance_analysis.core.time import utc_isoformat, utc_now
from finance_analysis.database.models.signal import Signal
from finance_analysis.database.repositories.signal import SignalRepository
from finance_analysis.database.repositories.stock import StockRepository
from finance_analysis.integrations.market_data.realtime_state.data_source import (
    get_default_sync_realtime_source,
)

logger = logging.getLogger(__name__)

EVALUATION_PERIODS = ("30m", "1h", "1d", "3d", "7d")
INTRADAY_PERIODS = {"30m": 30, "1h": 60}
DAILY_PERIODS = {"1d": 1, "3d": 3, "7d": 7}
MARKET_TIMEZONES = {
    "CN": ZoneInfo("Asia/Shanghai"),
    "US": ZoneInfo("America/New_York"),
}
DEFAULT_BATCH_SIZE = 200
MAX_SIGNAL_AGE = timedelta(days=15)
REDIS_BAR_READ_LIMIT = 420


def build_initial_evaluation(*, supports_intraday: bool) -> dict[str, Any]:
    if supports_intraday:
        return {}
    return {
        "30m": {"status": "not_applicable", "reason": "non_intraday_signal"},
        "1h": {"status": "not_applicable", "reason": "non_intraday_signal"},
    }


class MinuteBarSource(Protocol):
    def get_stored_bars(
        self,
        symbol: str,
        count: int,
        *,
        market_type: str,
    ) -> list[dict[str, Any]]: ...


@dataclass
class SignalEvaluationStats:
    market: str
    cutoff_time: datetime
    scanned_signals: int = 0
    fully_skipped_signals: int = 0
    not_applicable_skipped: int = 0
    data_not_mature: int = 0
    updated_signals: int = 0
    failed: int = 0
    added: dict[str, int] = field(default_factory=lambda: {period: 0 for period in EVALUATION_PERIODS})

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "market": self.market,
            "cutoff_time": utc_isoformat(self.cutoff_time),
            "scanned_signals": self.scanned_signals,
            "fully_skipped_signals": self.fully_skipped_signals,
            "not_applicable_skipped": self.not_applicable_skipped,
            "data_not_mature": self.data_not_mature,
            "updated_signals": self.updated_signals,
            "failed": self.failed,
        }
        result.update({f"{period}_added": count for period, count in self.added.items()})
        return result


class SignalEvaluationService:
    def __init__(
        self,
        *,
        signal_repository: SignalRepository | None = None,
        stock_repository: StockRepository | None = None,
        minute_bar_source: MinuteBarSource | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.signals = signal_repository or SignalRepository()
        self.stocks = stock_repository or StockRepository()
        self.minute_bars = minute_bar_source or get_default_sync_realtime_source()
        self.batch_size = max(1, int(batch_size))

    def evaluate_signals(
        self,
        *,
        market: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_market = market.upper()
        if normalized_market not in MARKET_TIMEZONES:
            raise ValueError("signal evaluation supports only CN and US")
        current = now or utc_now()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        cutoff = current.astimezone(timezone.utc) - MAX_SIGNAL_AGE
        stats = SignalEvaluationStats(market=normalized_market, cutoff_time=cutoff)
        cursor: tuple[datetime, int] | None = None

        while True:
            page = self.signals.list_for_evaluation(
                market=normalized_market,
                signal_at_from=cutoff,
                limit=self.batch_size,
                cursor=cursor,
            )
            if not page:
                break
            for signal in page:
                stats.scanned_signals += 1
                self._evaluate_signal(signal, current=current, stats=stats)
            last = page[-1]
            cursor = (last.signal_at, int(last.id))
            if len(page) < self.batch_size:
                break

        result = stats.to_dict()
        logger.info("signal_evaluation_%s result=%s", normalized_market.lower(), result)
        return result

    def _evaluate_signal(
        self,
        signal: Signal,
        *,
        current: datetime,
        stats: SignalEvaluationStats,
    ) -> None:
        evaluation = dict(signal.evaluation or {})
        missing = [period for period in EVALUATION_PERIODS if period not in evaluation]
        stats.not_applicable_skipped += sum(
            1
            for period in EVALUATION_PERIODS
            if _is_not_applicable(evaluation.get(period))
        )
        if not missing:
            stats.fully_skipped_signals += 1
            return

        changed_periods: list[str] = []
        intraday_missing = [period for period in INTRADAY_PERIODS if period in missing]
        daily_missing = [period for period in DAILY_PERIODS if period in missing]

        bars: list[dict[str, Any]] | None = None
        if intraday_missing:
            try:
                bars = self.minute_bars.get_stored_bars(
                    signal.code,
                    REDIS_BAR_READ_LIMIT,
                    market_type=signal.market,
                )
                bars = _bars_after_signal(bars, signal.signal_at)
            except Exception as exc:
                logger.exception("Signal %s minute bars failed: %s", signal.id, exc)
                stats.failed += len(intraday_missing)

        if bars is not None:
            for period in intraday_missing:
                try:
                    required = INTRADAY_PERIODS[period]
                    if len(bars) < required:
                        stats.data_not_mature += 1
                        continue
                    evaluation[period] = _build_result(
                        initial_price=signal.price,
                        bars=bars[:required],
                        current=current,
                    )
                    changed_periods.append(period)
                except Exception as exc:
                    stats.failed += 1
                    logger.exception("Signal %s period %s failed: %s", signal.id, period, exc)

        daily_bars: Sequence[Any] | None = None
        if daily_missing:
            try:
                signal_date = signal.signal_at.astimezone(MARKET_TIMEZONES[signal.market]).date()
                daily_bars = self.stocks.get_forward_bars(
                    code=signal.code,
                    analysis_date=signal_date,
                    eval_window_days=max(DAILY_PERIODS[period] for period in daily_missing),
                    market=signal.market,
                )
            except Exception as exc:
                logger.exception("Signal %s daily bars failed: %s", signal.id, exc)
                stats.failed += len(daily_missing)

        if daily_bars is not None:
            for period in daily_missing:
                try:
                    required = DAILY_PERIODS[period]
                    if len(daily_bars) < required:
                        stats.data_not_mature += 1
                        continue
                    evaluation[period] = _build_result(
                        initial_price=signal.price,
                        bars=daily_bars[:required],
                        current=current,
                    )
                    changed_periods.append(period)
                except Exception as exc:
                    stats.failed += 1
                    logger.exception("Signal %s period %s failed: %s", signal.id, period, exc)

        if changed_periods:
            try:
                self.signals.update_evaluation(int(signal.id), evaluation)
                stats.updated_signals += 1
                for period in changed_periods:
                    stats.added[period] += 1
            except Exception as exc:
                stats.failed += 1
                logger.exception("Signal %s evaluation update failed: %s", signal.id, exc)


def _is_not_applicable(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") == "not_applicable"


def _bars_after_signal(
    bars: Sequence[dict[str, Any]],
    signal_at: datetime,
) -> list[dict[str, Any]]:
    signal_utc = signal_at.astimezone(timezone.utc)
    result = []
    for bar in bars:
        timestamp = _parse_timestamp(bar.get("timestamp"))
        if timestamp is not None and timestamp.astimezone(timezone.utc) >= signal_utc:
            result.append({**bar, "_timestamp": timestamp})
    return sorted(result, key=lambda item: item["_timestamp"])


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _value(bar: Any, field: str) -> float:
    raw = bar.get(field) if isinstance(bar, dict) else getattr(bar, field)
    value = float(raw)
    if value <= 0:
        raise ValueError(f"invalid {field}: {value}")
    return value


def _build_result(
    *,
    initial_price: float,
    bars: Sequence[Any],
    current: datetime,
) -> dict[str, Any]:
    if initial_price <= 0 or not bars:
        raise ValueError("evaluation requires a positive signal price and at least one bar")
    price = _value(bars[-1], "close")
    highest = max(_value(bar, "high") for bar in bars)
    lowest = min(_value(bar, "low") for bar in bars)

    def change(value: float) -> float:
        return round((value / initial_price - 1) * 100, 4)

    return {
        "price": price,
        "return_pct": change(price),
        "max_return_pct": change(highest),
        "min_return_pct": change(lowest),
        "evaluated_at": utc_isoformat(current),
    }


def evaluate_signals(*, market: str, now: datetime | None = None) -> dict[str, Any]:
    return SignalEvaluationService().evaluate_signals(market=market, now=now)


__all__ = [
    "EVALUATION_PERIODS",
    "SignalEvaluationService",
    "SignalEvaluationStats",
    "build_initial_evaluation",
    "evaluate_signals",
]

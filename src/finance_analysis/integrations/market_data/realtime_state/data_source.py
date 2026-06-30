"""Validated downstream access to market-streamer realtime state."""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Generic, TypeVar

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.providers.longbridge.market import _to_longbridge_symbol
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.integrations.market_data.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from finance_analysis.market_stream.config import (
    MarketStreamConfig,
    latest_completed_bar_time,
    market_spec,
    market_timezone,
)
from finance_analysis.stocks.markets import MarketType, normalize_market_type

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RealtimeReadPolicy:
    heartbeat_max_age: timedelta = timedelta(seconds=15)
    quote_max_age: timedelta = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class MarketDataLookup(Generic[T]):
    data: T | None
    fallback_reason: str | None = None


class RealtimeMarketDataSource:
    """Read and validate Redis state before exposing it to analysis code."""

    _HEALTHY_STREAMER_STATUSES = frozenset({"READY", "DEGRADED"})
    _QUOTE_SUBSCRIPTION_STATUSES = frozenset({"ACTIVE", "INSUFFICIENT_HISTORY", "WARMING"})
    _BAR_SUBSCRIPTION_STATUSES = frozenset({"ACTIVE", "INSUFFICIENT_HISTORY"})

    def __init__(
        self,
        repository: RealtimeStateRepository,
        *,
        policy: RealtimeReadPolicy | None = None,
    ) -> None:
        self.repository = repository
        self.policy = policy or RealtimeReadPolicy()

    async def close(self) -> None:
        await self.repository.close()

    async def get_quote(
        self,
        symbol: str,
        *,
        market_type: MarketType | None = None,
        now: datetime | None = None,
    ) -> UnifiedRealtimeQuote | None:
        return (await self.get_quote_lookup(symbol, market_type=market_type, now=now)).data

    async def get_quote_lookup(
        self,
        symbol: str,
        *,
        market_type: MarketType | None = None,
        now: datetime | None = None,
    ) -> MarketDataLookup[UnifiedRealtimeQuote]:
        current = _aware_utc(now)
        target = _target(symbol, market_type)
        if target is None:
            return self._miss(symbol, "invalid_symbol")
        canonical_symbol, normalized_market = target
        try:
            reason = await self._availability_reason(
                canonical_symbol,
                normalized_market,
                current,
                allowed_statuses=self._QUOTE_SUBSCRIPTION_STATUSES,
            )
            if reason:
                return self._miss(canonical_symbol, reason)
            quote = await self.repository.get_quote(canonical_symbol)
        except Exception as exc:
            logger.warning(
                "symbol=%s source=market_streamer fallback_reason=redis_error error=%s",
                canonical_symbol,
                exc,
            )
            return MarketDataLookup(None, "redis_error")

        reason = _quote_invalid_reason(quote, canonical_symbol, current, self.policy.quote_max_age)
        if reason:
            return self._miss(canonical_symbol, reason)
        result = _quote_to_unified(quote, requested_symbol=symbol)
        logger.info("symbol=%s source=market_streamer quote=1", canonical_symbol)
        return MarketDataLookup(result)

    async def get_recent_bars(
        self,
        symbol: str,
        count: int,
        *,
        market_type: MarketType | None = None,
        minimum_count: int = 1,
        include_incomplete: bool = False,
        now: datetime | None = None,
    ) -> list[dict[str, Any]] | None:
        lookup = await self.get_recent_bars_lookup(
            symbol,
            count,
            market_type=market_type,
            minimum_count=minimum_count,
            include_incomplete=include_incomplete,
            now=now,
        )
        return lookup.data

    async def get_recent_bars_lookup(
        self,
        symbol: str,
        count: int,
        *,
        market_type: MarketType | None = None,
        minimum_count: int = 1,
        include_incomplete: bool = False,
        now: datetime | None = None,
    ) -> MarketDataLookup[list[dict[str, Any]]]:
        current = _aware_utc(now)
        target = _target(symbol, market_type)
        if target is None:
            return self._miss(symbol, "invalid_symbol")
        canonical_symbol, normalized_market = target
        requested_count = max(1, int(count))
        required_count = max(1, min(int(minimum_count), requested_count))
        try:
            reason = await self._availability_reason(
                canonical_symbol,
                normalized_market,
                current,
                allowed_statuses=self._BAR_SUBSCRIPTION_STATUSES,
            )
            if reason:
                return self._miss(canonical_symbol, reason)
            bars = await self.repository.get_recent_bars(canonical_symbol, requested_count)
            current_candle = None
            if include_incomplete:
                current_candle = await self.repository.get_current_candle(canonical_symbol)
        except Exception as exc:
            logger.warning(
                "symbol=%s source=market_streamer fallback_reason=redis_error error=%s",
                canonical_symbol,
                exc,
            )
            return MarketDataLookup(None, "redis_error")

        valid, reason = _validated_bars(
            bars,
            symbol=canonical_symbol,
            market_type=normalized_market,
            minimum_count=required_count,
            now=current,
        )
        if reason:
            return self._miss(canonical_symbol, reason)
        if include_incomplete and current_candle is not None:
            valid = _merge_current(valid, current_candle, canonical_symbol, normalized_market, current)
        result = [_candle_to_bar(candle, normalized_market) for candle in valid[-requested_count:]]
        logger.info("symbol=%s source=market_streamer bars=%s", canonical_symbol, len(result))
        return MarketDataLookup(result)

    async def get_stored_bars(
        self,
        symbol: str,
        count: int,
        *,
        market_type: MarketType,
    ) -> list[dict[str, Any]]:
        """Read confirmed Redis bars without requiring a live market heartbeat.

        Post-close jobs need the stored history after the streamer has stopped.
        Unlike ``get_recent_bars``, this method intentionally keeps bars from
        multiple trading dates so a late-session signal can mature next session.
        """
        target = _target(symbol, market_type)
        if target is None:
            return []
        canonical_symbol, normalized_market = target
        bars = await self.repository.get_recent_bars(canonical_symbol, max(1, int(count)))
        spec = market_spec(normalized_market)
        by_identity: dict[tuple[datetime, str], CandleState] = {}
        for bar in bars:
            local_time = (
                bar.bar_time.astimezone(spec.timezone).time()
                if bar.bar_time.tzinfo
                else None
            )
            if (
                bar.symbol != canonical_symbol
                or bar.bar_time.tzinfo is None
                or not bar.confirmed
                or not bar.is_valid()
                or local_time is None
                or not any(start <= local_time < end for start, end in spec.regular_sessions)
            ):
                continue
            existing = by_identity.get(bar.identity)
            if existing is None or _prefer_candle(bar, existing):
                by_identity[bar.identity] = bar
        return [
            _candle_to_bar(bar, normalized_market)
            for bar in sorted(by_identity.values(), key=lambda item: item.bar_time)
        ]

    async def _availability_reason(
        self,
        symbol: str,
        market_type: MarketType,
        now: datetime,
        *,
        allowed_statuses: frozenset[str],
    ) -> str | None:
        heartbeat = await self.repository.get_heartbeat()
        if not heartbeat:
            return "missing_heartbeat"
        if str(heartbeat.get("status") or "").upper() not in self._HEALTHY_STREAMER_STATUSES:
            return "unhealthy_heartbeat"
        heartbeat_at = _parse_datetime(heartbeat.get("updated_at"))
        if (
            heartbeat_at is None
            or now - heartbeat_at > self.policy.heartbeat_max_age
            or heartbeat_at - now > timedelta(seconds=5)
        ):
            return "stale_heartbeat"

        subscription = await self.repository.get_subscription(symbol)
        if not subscription:
            return "missing_subscription"
        if str(subscription.get("status") or "").upper() not in allowed_statuses:
            return "subscription_not_ready"
        subscription_market = str(subscription.get("market_type") or "").strip()
        if not subscription_market or normalize_market_type(subscription_market, symbol) != market_type:
            return "market_mismatch"
        return None

    @staticmethod
    def _miss(symbol: str, reason: str) -> MarketDataLookup[Any]:
        logger.info("symbol=%s source=market_streamer fallback_reason=%s", symbol, reason)
        return MarketDataLookup(None, reason)


class SyncRealtimeMarketDataSource:
    """Synchronous facade backed by one dedicated asyncio event-loop thread."""

    def __init__(
        self,
        source_factory: Callable[[], RealtimeMarketDataSource] | None = None,
        *,
        operation_timeout_seconds: float = 3.0,
    ) -> None:
        self._source_factory = source_factory or _default_async_source
        self.operation_timeout_seconds = max(0.1, float(operation_timeout_seconds))
        self._source: RealtimeMarketDataSource | None = None
        self._pid = os.getpid()
        self._closed = False
        self._local = threading.local()
        self._start_runner()

    def _start_runner(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._started = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, name="realtime-market-data", daemon=True)
        self._thread.start()
        self._started.wait()

    def _ensure_process(self) -> None:
        """Recreate loop-owned resources after a Celery prefork."""
        current_pid = os.getpid()
        if current_pid == self._pid:
            return
        self._pid = current_pid
        self._source = None
        self._closed = False
        self._local = threading.local()
        self._start_runner()

    @property
    def fallback_reason(self) -> str | None:
        return getattr(self._local, "fallback_reason", None)

    def get_quote(
        self,
        symbol: str,
        *,
        market_type: MarketType | None = None,
        now: datetime | None = None,
    ) -> UnifiedRealtimeQuote | None:
        lookup = self._submit(self._quote_lookup(symbol, market_type=market_type, now=now))
        self._local.fallback_reason = lookup.fallback_reason
        return lookup.data

    def get_recent_bars(
        self,
        symbol: str,
        count: int,
        *,
        market_type: MarketType | None = None,
        minimum_count: int = 1,
        include_incomplete: bool = False,
        now: datetime | None = None,
    ) -> list[dict[str, Any]] | None:
        lookup = self._submit(
            self._bars_lookup(
                symbol,
                count,
                market_type=market_type,
                minimum_count=minimum_count,
                include_incomplete=include_incomplete,
                now=now,
            )
        )
        self._local.fallback_reason = lookup.fallback_reason
        return lookup.data

    def get_stored_bars(
        self,
        symbol: str,
        count: int,
        *,
        market_type: MarketType,
    ) -> list[dict[str, Any]]:
        return self._submit(self._stored_bars(symbol, count, market_type=market_type))

    def close(self) -> None:
        if self._closed:
            return
        if os.getpid() != self._pid:
            # A forked child cannot drive or close the parent's event loop.
            self._closed = True
            return
        try:
            self._submit(self._close_source())
        finally:
            self._closed = True
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)
            if not self._thread.is_alive():
                self._loop.close()

    async def _quote_lookup(self, symbol: str, **kwargs: Any) -> MarketDataLookup[UnifiedRealtimeQuote]:
        source = self._get_source()
        return await source.get_quote_lookup(symbol, **kwargs)

    async def _bars_lookup(self, symbol: str, count: int, **kwargs: Any) -> MarketDataLookup[list[dict[str, Any]]]:
        source = self._get_source()
        return await source.get_recent_bars_lookup(symbol, count, **kwargs)

    async def _stored_bars(self, symbol: str, count: int, **kwargs: Any) -> list[dict[str, Any]]:
        source = self._get_source()
        return await source.get_stored_bars(symbol, count, **kwargs)

    async def _close_source(self) -> None:
        if self._source is not None:
            await self._source.close()

    def _get_source(self) -> RealtimeMarketDataSource:
        if self._source is None:
            self._source = self._source_factory()
        return self._source

    def _submit(self, coroutine: Any) -> Any:
        self._ensure_process()
        if self._closed:
            coroutine.close()
            raise RuntimeError("realtime market data source is closed")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout=self.operation_timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(
                f"realtime market data read exceeded {self.operation_timeout_seconds:.1f}s"
            ) from exc

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()


def _default_async_source() -> RealtimeMarketDataSource:
    config = MarketStreamConfig.from_env()
    return RealtimeMarketDataSource(RealtimeStateRepository.from_url(config.redis_url, bar_limit=config.bar_limit))


@lru_cache(maxsize=1)
def _cached_default_sync_realtime_source() -> SyncRealtimeMarketDataSource:
    return SyncRealtimeMarketDataSource()


def get_default_sync_realtime_source() -> SyncRealtimeMarketDataSource:
    source = _cached_default_sync_realtime_source()
    source._ensure_process()
    return source


def _close_default_source() -> None:
    if _cached_default_sync_realtime_source.cache_info().currsize:
        _cached_default_sync_realtime_source().close()


atexit.register(_close_default_source)


def _aware_utc(value: datetime | None) -> datetime:
    current = value or utc_now()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _target(symbol: str, market_type: MarketType | None) -> tuple[str, MarketType] | None:
    canonical = _to_longbridge_symbol(symbol)
    if not canonical:
        return None
    normalized_market = normalize_market_type(market_type, canonical)
    expected_suffixes = {"CN": (".SH", ".SZ"), "HK": (".HK",), "US": (".US",)}
    if not canonical.endswith(expected_suffixes[normalized_market]):
        return None
    return canonical, normalized_market


def _quote_invalid_reason(
    quote: QuoteState | None,
    symbol: str,
    now: datetime,
    max_age: timedelta,
) -> str | None:
    if quote is None:
        return "redis_missing"
    if quote.symbol != symbol or quote.last_price is None or quote.last_price <= 0:
        return "invalid_quote"
    if quote.received_at is None or quote.received_at.tzinfo is None:
        return "invalid_quote_time"
    age = now - quote.received_at.astimezone(timezone.utc)
    if age > max_age or age < -timedelta(seconds=5):
        return "stale_quote"
    return None


def _quote_to_unified(quote: QuoteState, *, requested_symbol: str) -> UnifiedRealtimeQuote:
    price = float(quote.last_price) if quote.last_price is not None else None
    previous = float(quote.pre_close) if quote.pre_close is not None else None
    change_amount = price - previous if price is not None and previous else None
    change_pct = change_amount / previous * 100 if change_amount is not None and previous else None
    amplitude = None
    if previous and quote.high is not None and quote.low is not None:
        amplitude = (float(quote.high) - float(quote.low)) / previous * 100
    return UnifiedRealtimeQuote(
        code=requested_symbol,
        source=RealtimeSource.MARKET_STREAMER,
        price=price,
        change_amount=round(change_amount, 4) if change_amount is not None else None,
        change_pct=round(change_pct, 2) if change_pct is not None else None,
        volume=quote.volume,
        amount=float(quote.turnover) if quote.turnover is not None else None,
        amplitude=round(amplitude, 2) if amplitude is not None else None,
        open_price=float(quote.open) if quote.open is not None else None,
        high=float(quote.high) if quote.high is not None else None,
        low=float(quote.low) if quote.low is not None else None,
        pre_close=previous,
    )


def _validated_bars(
    bars: list[CandleState],
    *,
    symbol: str,
    market_type: MarketType,
    minimum_count: int,
    now: datetime,
) -> tuple[list[CandleState], str | None]:
    trading_date = now.astimezone(market_timezone(market_type)).date()
    by_identity: dict[tuple[datetime, str], CandleState] = {}
    for bar in bars:
        if (
            bar.symbol != symbol
            or bar.bar_time.tzinfo is None
            or not bar.is_valid()
            or not bar.confirmed
            or bar.bar_time.astimezone(market_timezone(market_type)).date() != trading_date
        ):
            continue
        existing = by_identity.get(bar.identity)
        if existing is None or _prefer_candle(bar, existing):
            by_identity[bar.identity] = bar
    valid = sorted(by_identity.values(), key=lambda item: item.bar_time)
    if len(valid) < minimum_count:
        return [], "insufficient_bars"
    expected = latest_completed_bar_time(now, market_type)
    if expected is None:
        return [], "outside_regular_session"
    latest = max((bar.bar_time for bar in valid if bar.confirmed), default=None)
    if latest is None or expected - latest.astimezone(timezone.utc) > market_spec(market_type).cache_gap_tolerance:
        return [], "stale_bars"
    return valid, None


def _merge_current(
    bars: list[CandleState],
    current: CandleState,
    symbol: str,
    market_type: MarketType,
    now: datetime,
) -> list[CandleState]:
    spec = market_spec(market_type)
    current_local = current.bar_time.astimezone(spec.timezone) if current.bar_time.tzinfo else None
    now_local = now.astimezone(spec.timezone)
    if (
        current.symbol != symbol
        or current.bar_time.tzinfo is None
        or current.received_at.tzinfo is None
        or not current.is_valid()
        or current_local is None
        or current_local.date() != now_local.date()
        or not any(start <= current_local.time() < end for start, end in spec.regular_sessions)
    ):
        return bars
    if current.confirmed:
        expected = latest_completed_bar_time(now, market_type)
        if expected is None or current.bar_time.astimezone(timezone.utc) > expected:
            return bars
    elif current_local.replace(second=0, microsecond=0) != now_local.replace(second=0, microsecond=0):
        return bars
    by_identity = {bar.identity: bar for bar in bars}
    existing = by_identity.get(current.identity)
    if existing is None or _prefer_candle(current, existing):
        by_identity[current.identity] = current
    return sorted(by_identity.values(), key=lambda item: item.bar_time)


def _prefer_candle(candidate: CandleState, existing: CandleState) -> bool:
    if candidate.confirmed != existing.confirmed:
        return candidate.confirmed
    return candidate.received_at >= existing.received_at


def _candle_to_bar(candle: CandleState, market_type: MarketType) -> dict[str, Any]:
    return {
        "timestamp": candle.bar_time.astimezone(market_timezone(market_type)).isoformat(),
        "open": float(candle.open),
        "high": float(candle.high),
        "low": float(candle.low),
        "close": float(candle.close),
        "volume": candle.volume,
        "turnover": float(candle.turnover) if candle.turnover is not None else None,
        "trade_session": candle.trade_session,
    }

"""Async Redis repository for realtime quotes, bars, subscriptions, and heartbeat."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Sequence

from redis.exceptions import WatchError

from finance_analysis.core.time import utc_isoformat
from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState, TrendState, unique_minute_bars
from finance_analysis.market_stream.patterns.models import PatternState
from finance_analysis.market_stream.config import US_MINUTE_LIMIT, US_MINUTE_WINDOW, market_trading_date, us_minute_cutoff


def _encode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return utc_isoformat(value) or ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _mapping(value: Any) -> dict[str, str]:
    source = asdict(value) if hasattr(value, "__dataclass_fields__") else dict(value)
    mapping = {key: _encode(item) for key, item in source.items()}
    if isinstance(value, CandleState):
        # This timestamp orders competing revisions, including retries within the same millisecond.
        mapping["received_at"] = value.received_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return mapping


def _candle_json(candle: CandleState) -> str:
    return json.dumps(_mapping(candle), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


class RealtimeStateRepository:
    """The only owner of realtime Redis keys and serialization rules."""

    def __init__(
        self,
        redis: Any,
        *,
        bar_limit: int = US_MINUTE_LIMIT,
        quote_ttl_seconds: int = 2 * 86400,
        bars_ttl_seconds: int = 3 * 86400,
        trend_ttl_seconds: int | None = None,
        pattern_ttl_seconds: int | None = None,
        removed_ttl_seconds: int = 2 * 3600,
        retain_session: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.redis = redis
        self.bar_limit = max(1, min(int(bar_limit), US_MINUTE_LIMIT))
        self.quote_ttl_seconds = quote_ttl_seconds
        self.bars_ttl_seconds = bars_ttl_seconds
        self.trend_ttl_seconds = trend_ttl_seconds or bars_ttl_seconds
        self.pattern_ttl_seconds = pattern_ttl_seconds or bars_ttl_seconds
        self.removed_ttl_seconds = removed_ttl_seconds
        self.retain_session = retain_session
        self.clock = clock

    def _ttl(self, symbol, day, default):
        if not self.retain_session or day is None:
            return default
        from finance_analysis.core.time import utc_now
        from finance_analysis.market_stream.session import cache_ttl

        market = "US" if symbol.endswith(".US") else "HK" if symbol.endswith(".HK") else "CN"
        return cache_ttl(market, day, utc_now())

    def _bar_ttl(self, symbol, stamp, received_at):
        if symbol.endswith(".US"):
            observed = max(received_at, self.clock()) if self.clock else received_at
            seconds = (stamp.astimezone(timezone.utc) + US_MINUTE_WINDOW + timedelta(minutes=1) - observed).total_seconds()
            return max(1, min(int(US_MINUTE_WINDOW.total_seconds()), int(seconds)))
        return self._ttl(symbol, stamp.date(), self.bars_ttl_seconds)

    async def record_pattern_event(self, pattern, observed_at):
        """Append immutable stage evidence at its detection time, never backdate confirmation."""
        signal = pattern.signal
        if signal is None:
            return
        key = keys.pattern_events_key(pattern.symbol)
        event_day = market_trading_date(signal.occurred_at, "US") if pattern.symbol.endswith(".US") else signal.trading_date
        field = f"{event_day}:{signal.pattern_type}:{signal.occurred_at.isoformat()}:{signal.stage}"
        payload = {**signal.to_dict(), "observed_at": utc_isoformat(observed_at)}
        previous = await self.redis.hgetall(key)
        if pattern.symbol.endswith(".US"):
            cutoff = utc_isoformat(us_minute_cutoff(observed_at))
            obsolete = [name for name, item in previous.items() if json.loads(item)["observed_at"] < cutoff]
        else:
            obsolete = [name for name in previous if not name.startswith(f"{signal.trading_date}:")]
        if obsolete:
            await self.redis.hdel(key, *obsolete)
        await self.redis.hsetnx(key, field, json.dumps(payload, ensure_ascii=False))
        ttl = self._ttl(pattern.symbol, signal.trading_date, self.pattern_ttl_seconds)
        await self.redis.expire(key, ttl)

    async def get_pattern_events(self, symbol, day, *, now=None):
        raw = await self.redis.hgetall(keys.pattern_events_key(symbol))
        events = [json.loads(value) for value in raw.values()]
        if symbol.endswith(".US") and now is not None:
            cutoff, end = utc_isoformat(us_minute_cutoff(now)), utc_isoformat(now)
            events = [event for event in events if cutoff <= event["observed_at"] <= end]
        else:
            events = [event for event in events if event.get("trading_date") == str(day)]
        return sorted(events, key=lambda event: event["observed_at"])

    async def clear_intraday(self, symbol):
        """Discard incompatible CN bars and indicators when changing acquisition semantics."""
        await self.redis.delete(
            keys.current_candle_key(symbol), keys.bars_index_key(symbol), keys.bars_data_key(symbol),
            keys.bars_revision_key(symbol),
            keys.trend_key(symbol), keys.pattern_key(symbol), keys.pattern_events_key(symbol),
        )

    async def replace_intraday_bars(self, symbol, bars):
        """Atomically publish a complete native CN window, retaining observed pattern events."""
        values = [bar for bar in bars if bar.symbol == symbol and bar.is_valid()]
        if not symbol.endswith((".SH", ".SZ", ".BJ")) or not values:
            raise ValueError("CN minute replacement requires valid CN candles")
        values = unique_minute_bars(values)[-self.bar_limit:]
        pipe = self.redis.pipeline(transaction=True)
        index_key, data_key = keys.bars_index_key(symbol), keys.bars_data_key(symbol)
        pipe.delete(index_key, data_key, keys.current_candle_key(symbol))
        for bar in values:
            if bar.confirmed:
                field = self._bar_field(bar)
                pipe.zadd(index_key, {field: bar.bar_time.timestamp()})
                pipe.hset(data_key, field, _candle_json(bar))
        pipe.hset(keys.current_candle_key(symbol), mapping=_mapping(values[-1]))
        from finance_analysis.market_stream.config import market_trading_date

        ttl = self._ttl(symbol, market_trading_date(values[-1].bar_time, "CN"), self.bars_ttl_seconds)
        for key in (index_key, data_key, keys.current_candle_key(symbol)):
            pipe.expire(key, ttl)
        pipe.set(keys.bars_revision_key(symbol), uuid.uuid4().hex, ex=ttl)
        await pipe.execute()

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> "RealtimeStateRepository":
        from redis.asyncio import Redis

        return cls(Redis.from_url(url, decode_responses=True), **kwargs)

    async def close(self) -> None:
        closer = getattr(self.redis, "aclose", None) or getattr(self.redis, "close", None)
        if closer is not None:
            result = closer()
            if hasattr(result, "__await__"):
                await result

    async def write_quote(self, quote: QuoteState) -> None:
        pipe = self.redis.pipeline(transaction=False)
        pipe.hset(keys.quote_key(quote.symbol), mapping=_mapping(quote))
        pipe.expire(keys.quote_key(quote.symbol), self._ttl(quote.symbol, quote.trading_date, self.quote_ttl_seconds))
        await pipe.execute()

    async def get_quote(self, symbol: str) -> QuoteState | None:
        raw = await self.redis.hgetall(keys.quote_key(symbol))
        return self._quote_from_mapping(symbol, raw) if raw else None

    async def get_quotes(self, symbols: Iterable[str]) -> dict[str, QuoteState]:
        """Load several quote hashes in one Redis round trip."""
        unique_symbols = list(dict.fromkeys(symbols))
        if not unique_symbols:
            return {}
        pipe = self.redis.pipeline(transaction=False)
        for symbol in unique_symbols:
            pipe.hgetall(keys.quote_key(symbol))
        values = await pipe.execute()
        quotes: dict[str, QuoteState] = {}
        for symbol, raw in zip(unique_symbols, values):
            if raw:
                quotes[symbol] = self._quote_from_mapping(symbol, raw)
        return quotes

    async def write_trend_state(self, trend: TrendState) -> None:
        await self.write_trend_states_batch({trend.symbol: trend})

    async def write_trend_states_batch(self, trends: Mapping[str, TrendState]) -> None:
        valid = {symbol: trend for symbol, trend in trends.items() if symbol and trend.symbol == symbol}
        if not valid:
            return
        pipe = self.redis.pipeline(transaction=False)
        for symbol, trend in valid.items():
            pipe.hset(keys.trend_key(symbol), mapping=_mapping(trend))
            pipe.expire(keys.trend_key(symbol), self._ttl(symbol, trend.trading_date, self.trend_ttl_seconds))
        await pipe.execute()

    async def get_trend_state(self, symbol: str) -> TrendState | None:
        raw = await self.redis.hgetall(keys.trend_key(symbol))
        return TrendState.from_mapping(raw) if raw else None

    async def get_trend_states(self, symbols: Iterable[str]) -> dict[str, TrendState]:
        unique_symbols = list(dict.fromkeys(symbols))
        if not unique_symbols:
            return {}
        pipe = self.redis.pipeline(transaction=False)
        for symbol in unique_symbols:
            pipe.hgetall(keys.trend_key(symbol))
        values = await pipe.execute()
        return {symbol: TrendState.from_mapping(raw) for symbol, raw in zip(unique_symbols, values) if raw}

    async def write_pattern_state(self, pattern: PatternState) -> None:
        await self.write_pattern_states_batch({pattern.symbol: pattern})

    async def write_pattern_states_batch(self, patterns: Mapping[str, PatternState]) -> None:
        valid = {symbol: pattern for symbol, pattern in patterns.items() if symbol and pattern.symbol == symbol}
        if not valid:
            return
        pipe = self.redis.pipeline(transaction=False)
        for symbol, pattern in valid.items():
            pipe.hset(keys.pattern_key(symbol), mapping=pattern.to_mapping())
            pipe.expire(keys.pattern_key(symbol), self._ttl(symbol, pattern.trading_date, self.pattern_ttl_seconds))
        await pipe.execute()

    async def get_pattern_state(self, symbol: str) -> PatternState | None:
        raw = await self.redis.hgetall(keys.pattern_key(symbol))
        return PatternState.from_mapping(raw) if raw else None

    async def get_pattern_states(self, symbols: Iterable[str]) -> dict[str, PatternState]:
        unique_symbols = list(dict.fromkeys(symbols))
        if not unique_symbols:
            return {}
        pipe = self.redis.pipeline(transaction=False)
        for symbol in unique_symbols:
            pipe.hgetall(keys.pattern_key(symbol))
        values = await pipe.execute()
        return {symbol: PatternState.from_mapping(raw) for symbol, raw in zip(unique_symbols, values) if raw}

    @staticmethod
    def _quote_from_mapping(symbol: str, raw: Mapping[str, Any]) -> QuoteState:
        quote = QuoteState(symbol=str(raw.get("symbol") or symbol))
        trading_date = _parse_date(raw.get("trading_date"))
        if trading_date is None:
            # Quotes written before trading_date existed cannot be assigned to
            # the current session safely. Deserialize them as uninitialized so
            # readers wait for the streamer's full snapshot instead of exposing
            # stale OHLC/reference fields.
            quote.event_time = _parse_datetime(raw.get("event_time"))
            quote.received_at = _parse_datetime(raw.get("received_at"))
            return quote
        quote.merge(
            {
                key: value
                for key, value in raw.items()
                if key not in {"symbol", "trading_date", "event_time", "received_at"} and value != ""
            },
            event_time=_parse_datetime(raw.get("event_time")),
            received_at=_parse_datetime(raw.get("received_at")),
            trading_date=trading_date,
        )
        return quote

    async def write_current_candle(self, candle: CandleState) -> None:
        pipe = self.redis.pipeline(transaction=False)
        pipe.hset(keys.current_candle_key(candle.symbol), mapping=_mapping(candle))
        pipe.expire(
            keys.current_candle_key(candle.symbol),
            self._bar_ttl(candle.symbol, candle.bar_time, candle.received_at),
        )
        await pipe.execute()

    async def get_current_candle(self, symbol: str) -> CandleState | None:
        raw = await self.redis.hgetall(keys.current_candle_key(symbol))
        return CandleState.from_mapping(raw) if raw else None

    async def get_intraday_snapshot(self, symbol):
        """Read history and current candle atomically from the same cache generation."""
        pipe = self.redis.pipeline(transaction=True)
        pipe.zrange(keys.bars_index_key(symbol), 0, -1)
        pipe.hgetall(keys.bars_data_key(symbol))
        pipe.hgetall(keys.current_candle_key(symbol))
        fields, history, current = await pipe.execute()
        lookup = set(fields) | {field.partition(":")[0] for field in fields if ":" in field}
        candles = (CandleState.from_mapping(json.loads(history[field])) for field in lookup if field in history)
        bars = unique_minute_bars(candles)[-self.bar_limit:]
        return bars, CandleState.from_mapping(current) if current else None

    async def upsert_bars(self, symbol: str, bars: Iterable[CandleState]) -> None:
        await self.upsert_bars_batch({symbol: bars})

    async def upsert_bars_batch(
        self,
        bars_by_symbol: Mapping[str, Iterable[CandleState]],
    ) -> None:
        batches = {}
        for symbol, bars in bars_by_symbol.items():
            valid = unique_minute_bars(bar for bar in bars if bar.symbol == symbol and bar.confirmed and bar.is_valid())
            if valid:
                batches[symbol] = valid
        if not batches:
            return
        # Warmup, live pushes and failed-write retries may overlap for the same minute.
        watched = [key for symbol in batches for key in (keys.bars_index_key(symbol), keys.bars_data_key(symbol))]
        async with self.redis.pipeline(transaction=True) as pipe:
            while True:
                try:
                    await pipe.watch(*watched)
                    changes = {}
                    for symbol, bars in batches.items():
                        changes[symbol] = await self._plan_bar_write(pipe, symbol, bars)
                    pipe.multi()
                    for symbol, (obsolete, updates, ttl) in changes.items():
                        index_key, data_key = keys.bars_index_key(symbol), keys.bars_data_key(symbol)
                        if obsolete:
                            pipe.zrem(index_key, *obsolete)
                            pipe.hdel(data_key, *obsolete)
                        if updates:
                            pipe.zadd(index_key, {field: bar.bar_time.timestamp() for field, bar in updates.items()})
                            pipe.hset(data_key, mapping={field: _candle_json(bar) for field, bar in updates.items()})
                        pipe.expire(index_key, ttl)
                        pipe.expire(data_key, ttl)
                        # Commit the revision together with the confirmed bars.
                        # A UUID avoids collisions after Redis cache expiration.
                        if obsolete or updates:
                            pipe.set(keys.bars_revision_key(symbol), uuid.uuid4().hex, ex=ttl)
                        else:
                            pipe.expire(keys.bars_revision_key(symbol), ttl)
                    await pipe.execute()
                    return
                except WatchError:
                    continue

    async def _plan_bar_write(self, pipe, symbol, incoming):
        """Merge legacy timestamp:session fields before counting the retained minutes."""
        from finance_analysis.market_stream.config import market_timezone

        indexed = await pipe.zrange(keys.bars_index_key(symbol), 0, -1)
        legacy = {field for field in indexed if ":" in field}
        changed = {self._bar_field(bar) for bar in incoming}
        # Read payloads only for legacy fields and minutes being updated.
        changed.update(field.partition(":")[0] for field in legacy)
        overlap = [field for field in indexed if field in legacy or field in changed]
        stored = await pipe.hmget(keys.bars_data_key(symbol), overlap) if overlap else []
        bars = [CandleState.from_mapping(json.loads(raw)) for raw in stored if raw]
        updates = {self._bar_field(bar): bar for bar in unique_minute_bars([*bars, *incoming])}

        minutes = sorted((set(indexed) - legacy) | updates.keys(), key=int)
        market = "US" if symbol.endswith(".US") else "HK" if symbol.endswith(".HK") else "CN"
        tz = market_timezone(market)
        day = datetime.fromtimestamp(int(minutes[-1]), tz).date()
        start = datetime.combine(day, time.min, tz).timestamp()
        if market == "US":
            newest = datetime.fromtimestamp(int(minutes[-1]), timezone.utc)
            observed = max(newest, *(bar.received_at for bar in incoming))
            if self.clock:
                observed = max(observed, self.clock())
            start = us_minute_cutoff(observed).timestamp()
            ttl = self._bar_ttl(symbol, newest, observed)
        else:
            ttl = self._ttl(symbol, day, self.bars_ttl_seconds)
        keep = {field for field in minutes[-self.bar_limit:] if int(field) >= start}
        return (
            set(indexed) - keep,
            {field: bar for field, bar in updates.items() if field in keep},
            ttl,
        )

    async def prune_us_minutes(self, symbols: Iterable[str], now: datetime) -> None:
        """Expire individual old minutes even during a halt, holiday or quiet session."""
        cutoff = us_minute_cutoff(now).timestamp()
        for symbol in sorted(set(symbols)):
            if not symbol.endswith(".US"):
                continue
            index, data = keys.bars_index_key(symbol), keys.bars_data_key(symbol)
            async with self.redis.pipeline(transaction=True) as pipe:
                while True:
                    try:
                        await pipe.watch(index, data)
                        obsolete = await pipe.zrangebyscore(index, 0, cutoff - 1)
                        if not obsolete:
                            break
                        ttl = await pipe.ttl(index)
                        pipe.multi()
                        pipe.zrem(index, *obsolete)
                        pipe.hdel(data, *obsolete)
                        # Invalidate Trader's versioned cache without extending the bar window.
                        pipe.set(keys.bars_revision_key(symbol), uuid.uuid4().hex, ex=max(1, min(ttl, int(US_MINUTE_WINDOW.total_seconds()))))
                        await pipe.execute()
                        break
                    except WatchError:
                        continue

    async def get_bar_revisions(self, symbols: Iterable[str]) -> dict[str, str | None]:
        unique = list(dict.fromkeys(symbols))
        if not unique:
            return {}
        pipe = self.redis.pipeline(transaction=False)
        for symbol in unique:
            pipe.get(keys.bars_revision_key(symbol))
        return dict(zip(unique, await pipe.execute(), strict=True))

    async def get_confirmed_bar_snapshots(
        self, symbols: Iterable[str],
    ) -> dict[str, tuple[str | None, list[CandleState]]]:
        """Read revisions and confirmed data atomically, in one batch round trip."""
        unique = list(dict.fromkeys(symbols))
        if not unique:
            return {}
        pipe = self.redis.pipeline(transaction=True)
        for symbol in unique:
            pipe.get(keys.bars_revision_key(symbol))
            pipe.zrange(keys.bars_index_key(symbol), 0, -1)
            pipe.hgetall(keys.bars_data_key(symbol))
        values = await pipe.execute()
        result = {}
        for index, symbol in enumerate(unique):
            revision, fields, raw = values[3 * index:3 * index + 3]
            # Respect the authoritative index (including legacy session-suffixed
            # entries); stray hash fields must not become strategy evidence.
            lookup = set(fields) | {field.partition(":")[0] for field in fields if ":" in field}
            bars = unique_minute_bars(
                bar for field in lookup if field in raw
                if (bar := CandleState.from_mapping(json.loads(raw[field]))).confirmed and bar.symbol == symbol
            )[-self.bar_limit:]
            result[symbol] = revision, bars
        return result

    async def get_recent_bars(self, symbol: str, count: int) -> list[CandleState]:
        if count <= 0:
            return []
        fields = await self.redis.zrange(keys.bars_index_key(symbol), -int(count), -1)
        if any(":" in field for field in fields):
            # Legacy duplicates could occupy several of the last count entries.
            fields = await self.redis.zrange(keys.bars_index_key(symbol), 0, -1)
        return (await self._load_bar_fields(symbol, fields))[-count:]

    async def get_bars_by_time(self, symbol: str, start: datetime, end: datetime) -> list[CandleState]:
        fields = await self.redis.zrangebyscore(keys.bars_index_key(symbol), start.timestamp(), end.timestamp())
        return await self._load_bar_fields(symbol, fields)

    async def _load_bar_fields(self, symbol: str, fields: Sequence[str]) -> list[CandleState]:
        if not fields:
            return []
        # A writer can migrate the index between ZRANGE and HMGET.
        lookup = list(fields)
        lookup.extend({field.partition(":")[0] for field in fields if ":" in field})
        values = await self.redis.hmget(keys.bars_data_key(symbol), lookup)
        bars = [CandleState.from_mapping(json.loads(value)) for value in values if value]
        return unique_minute_bars(bars)

    @staticmethod
    def _bar_field(bar: CandleState) -> str:
        return str(int(bar.bar_time.timestamp()))

    async def write_subscription(
        self,
        symbol: str,
        state: Mapping[str, Any],
        *,
        ttl_seconds: int,
    ) -> None:
        mapping = {"symbol": symbol, **state}
        pipe = self.redis.pipeline(transaction=False)
        pipe.hset(keys.subscription_key(symbol), mapping=_mapping(mapping))
        pipe.expire(keys.subscription_key(symbol), ttl_seconds)
        await pipe.execute()

    async def get_subscription(self, symbol: str) -> dict[str, str] | None:
        state = await self.redis.hgetall(keys.subscription_key(symbol))
        return dict(state) if state else None

    async def refresh_subscription_ttls(
        self,
        symbols: Iterable[str],
        *,
        ttl_seconds: int,
    ) -> None:
        unique_symbols = sorted(set(symbols))
        if not unique_symbols:
            return
        pipe = self.redis.pipeline(transaction=False)
        for symbol in unique_symbols:
            pipe.expire(keys.subscription_key(symbol), ttl_seconds)
        await pipe.execute()

    async def write_heartbeat(self, state: Mapping[str, Any], *, ttl_seconds: int = 30) -> None:
        pipe = self.redis.pipeline(transaction=False)
        pipe.hset(keys.STREAMER_HEARTBEAT_KEY, mapping=_mapping(state))
        pipe.expire(keys.STREAMER_HEARTBEAT_KEY, ttl_seconds)
        await pipe.execute()

    async def get_heartbeat(self) -> dict[str, str] | None:
        state = await self.redis.hgetall(keys.STREAMER_HEARTBEAT_KEY)
        return dict(state) if state else None

    async def write_batch(
        self,
        quotes: Mapping[str, QuoteState],
        current_candles: Mapping[str, CandleState],
        trends: Mapping[str, TrendState] | None = None,
        patterns: Mapping[str, PatternState] | None = None,
    ) -> None:
        if not quotes and not current_candles and not trends and not patterns:
            return
        pipe = self.redis.pipeline(transaction=False)
        for symbol, quote in quotes.items():
            pipe.hset(keys.quote_key(symbol), mapping=_mapping(quote))
            pipe.expire(keys.quote_key(symbol), self._ttl(symbol, quote.trading_date, self.quote_ttl_seconds))
        for symbol, candle in current_candles.items():
            pipe.hset(keys.current_candle_key(symbol), mapping=_mapping(candle))
            pipe.expire(
                keys.current_candle_key(symbol), self._bar_ttl(symbol, candle.bar_time, candle.received_at)
            )
        for symbol, trend in (trends or {}).items():
            if trend.symbol != symbol:
                continue
            pipe.hset(keys.trend_key(symbol), mapping=_mapping(trend))
            pipe.expire(keys.trend_key(symbol), self._ttl(symbol, trend.trading_date, self.trend_ttl_seconds))
        for symbol, pattern in (patterns or {}).items():
            if pattern.symbol != symbol:
                continue
            pipe.hset(keys.pattern_key(symbol), mapping=pattern.to_mapping())
            pipe.expire(keys.pattern_key(symbol), self._ttl(symbol, pattern.trading_date, self.pattern_ttl_seconds))
        await pipe.execute()

    async def expire_symbol_cache(self, symbol: str, *, ttl_seconds: int | None = None) -> None:
        ttl_seconds = ttl_seconds or self.removed_ttl_seconds
        pipe = self.redis.pipeline(transaction=False)
        for key in (
            keys.quote_key(symbol),
            keys.current_candle_key(symbol),
            keys.bars_index_key(symbol),
            keys.bars_data_key(symbol),
            keys.bars_revision_key(symbol),
            keys.trend_key(symbol),
            keys.pattern_key(symbol),
            keys.pattern_events_key(symbol),
            keys.subscription_key(symbol),
        ):
            pipe.expire(key, ttl_seconds)
        await pipe.execute()

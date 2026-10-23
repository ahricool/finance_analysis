"""Async Redis repository for realtime quotes, bars, subscriptions, and heartbeat."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from finance_analysis.core.time import utc_isoformat
from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState, TrendState
from finance_analysis.market_stream.patterns.models import PatternState


def _encode(value: Any) -> str:
    if value is None:
        return ""
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
    return {key: _encode(item) for key, item in source.items()}


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
        bar_limit: int = 420,
        quote_ttl_seconds: int = 2 * 86400,
        bars_ttl_seconds: int = 3 * 86400,
        trend_ttl_seconds: int | None = None,
        pattern_ttl_seconds: int | None = None,
        removed_ttl_seconds: int = 2 * 3600,
        retain_session: bool = False,
    ) -> None:
        self.redis = redis
        self.bar_limit = max(1, min(int(bar_limit), 1000))
        self.quote_ttl_seconds = quote_ttl_seconds
        self.bars_ttl_seconds = bars_ttl_seconds
        self.trend_ttl_seconds = trend_ttl_seconds or bars_ttl_seconds
        self.pattern_ttl_seconds = pattern_ttl_seconds or bars_ttl_seconds
        self.removed_ttl_seconds = removed_ttl_seconds
        self.retain_session = retain_session

    def _ttl(self, symbol, day, default):
        if not self.retain_session or day is None:
            return default
        from finance_analysis.core.time import utc_now
        from finance_analysis.market_stream.session import cache_ttl

        market = "US" if symbol.endswith(".US") else "HK" if symbol.endswith(".HK") else "CN"
        return cache_ttl(market, day, utc_now())

    async def record_pattern_event(self, pattern, observed_at):
        """Append immutable stage evidence at its detection time, never backdate confirmation."""
        signal = pattern.signal
        if signal is None:
            return
        key = keys.pattern_events_key(pattern.symbol)
        field = f"{signal.trading_date}:{signal.pattern_type}:{signal.occurred_at.isoformat()}:{signal.stage}"
        payload = {**signal.to_dict(), "observed_at": utc_isoformat(observed_at)}
        previous = await self.redis.hgetall(key)
        obsolete = [name for name in previous if not name.startswith(f"{signal.trading_date}:")]
        if obsolete:
            await self.redis.hdel(key, *obsolete)
        await self.redis.hsetnx(key, field, json.dumps(payload, ensure_ascii=False))
        ttl = self._ttl(pattern.symbol, signal.trading_date, self.pattern_ttl_seconds)
        await self.redis.expire(key, ttl)

    async def get_pattern_events(self, symbol, day):
        raw = await self.redis.hgetall(keys.pattern_events_key(symbol))
        events = [json.loads(value) for value in raw.values()]
        return sorted(
            (event for event in events if event.get("trading_date") == str(day)), key=lambda event: event["observed_at"]
        )

    async def clear_intraday(self, symbol):
        """Discard incompatible CN bars and indicators when changing acquisition semantics."""
        await self.redis.delete(
            keys.current_candle_key(symbol), keys.bars_index_key(symbol), keys.bars_data_key(symbol),
            keys.trend_key(symbol), keys.pattern_key(symbol), keys.pattern_events_key(symbol),
        )

    async def replace_intraday_bars(self, symbol, bars):
        """Atomically publish a complete native CN window, retaining observed pattern events."""
        values = [bar for bar in bars if bar.symbol == symbol and bar.is_valid()]
        if not symbol.endswith((".SH", ".SZ", ".BJ")) or not values:
            raise ValueError("CN minute replacement requires valid CN candles")
        values = sorted(values, key=lambda bar: bar.bar_time)[-self.bar_limit:]
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
            self._ttl(candle.symbol, candle.bar_time.date(), self.bars_ttl_seconds),
        )
        await pipe.execute()

    async def get_current_candle(self, symbol: str) -> CandleState | None:
        raw = await self.redis.hgetall(keys.current_candle_key(symbol))
        return CandleState.from_mapping(raw) if raw else None

    async def get_intraday_snapshot(self, symbol):
        """Read CN history and current candle from the same published source generation."""
        pipe = self.redis.pipeline(transaction=True)
        pipe.hgetall(keys.bars_data_key(symbol))
        pipe.hgetall(keys.current_candle_key(symbol))
        history, current = await pipe.execute()
        bars = sorted((CandleState.from_mapping(json.loads(raw)) for raw in history.values()),
                      key=lambda bar: bar.bar_time)[-self.bar_limit:]
        return bars, CandleState.from_mapping(current) if current else None

    async def upsert_bars(self, symbol: str, bars: Iterable[CandleState]) -> None:
        await self.upsert_bars_batch({symbol: bars})

    async def upsert_bars_batch(
        self,
        bars_by_symbol: Mapping[str, Iterable[CandleState]],
    ) -> None:
        valid_by_symbol = {
            symbol: {
                self._bar_field(bar): bar for bar in bars if bar.symbol == symbol and bar.confirmed and bar.is_valid()
            }
            for symbol, bars in bars_by_symbol.items()
        }
        valid_by_symbol = {symbol: bars for symbol, bars in valid_by_symbol.items() if bars}
        if not valid_by_symbol:
            return
        pipe = self.redis.pipeline(transaction=False)
        for symbol, valid in valid_by_symbol.items():
            index_key = keys.bars_index_key(symbol)
            data_key = keys.bars_data_key(symbol)
            # Keep one market session, even when a late packet from yesterday arrives.
            latest = await self.get_recent_bars(symbol, 1)
            market = "US" if symbol.endswith(".US") else "HK" if symbol.endswith(".HK") else "CN"
            from finance_analysis.market_stream.config import market_trading_date, market_timezone
            from datetime import time

            newest = max(bar.bar_time for bar in valid.values())
            if latest:
                newest = max(newest, latest[-1].bar_time)
            day = market_trading_date(newest, market)
            start = datetime.combine(day, time.min, market_timezone(market))
            obsolete = await self.redis.zrangebyscore(index_key, float("-inf"), start.timestamp() - 0.001)
            if obsolete:
                pipe.zrem(index_key, *obsolete)
                pipe.hdel(data_key, *obsolete)
            for field, bar in valid.items():
                if market_trading_date(bar.bar_time, market) != day:
                    continue
                pipe.zadd(index_key, {field: bar.bar_time.timestamp()})
                pipe.hset(data_key, field, _candle_json(bar))
            ttl = self._ttl(symbol, day, self.bars_ttl_seconds)
            pipe.expire(index_key, ttl)
            pipe.expire(data_key, ttl)
        await pipe.execute()
        for symbol in valid_by_symbol:
            await self._trim_bars(keys.bars_index_key(symbol), keys.bars_data_key(symbol))

    async def _trim_bars(self, index_key: str, data_key: str) -> None:
        count = int(await self.redis.zcard(index_key))
        excess = count - self.bar_limit
        if excess <= 0:
            return
        fields = await self.redis.zrange(index_key, 0, excess - 1)
        if not fields:
            return
        pipe = self.redis.pipeline(transaction=False)
        pipe.zrem(index_key, *fields)
        pipe.hdel(data_key, *fields)
        await pipe.execute()

    async def get_recent_bars(self, symbol: str, count: int) -> list[CandleState]:
        if count <= 0:
            return []
        fields = await self.redis.zrange(keys.bars_index_key(symbol), -int(count), -1)
        return await self._load_bar_fields(symbol, fields)

    async def get_bars_by_time(self, symbol: str, start: datetime, end: datetime) -> list[CandleState]:
        fields = await self.redis.zrangebyscore(keys.bars_index_key(symbol), start.timestamp(), end.timestamp())
        return await self._load_bar_fields(symbol, fields)

    async def _load_bar_fields(self, symbol: str, fields: Sequence[str]) -> list[CandleState]:
        if not fields:
            return []
        values = await self.redis.hmget(keys.bars_data_key(symbol), list(fields))
        bars = [CandleState.from_mapping(json.loads(value)) for value in values if value]
        return sorted(bars, key=lambda item: item.bar_time)

    @staticmethod
    def _bar_field(bar: CandleState) -> str:
        session = (bar.trade_session or "").replace(":", "_")
        return f"{int(bar.bar_time.timestamp())}:{session}"

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
                keys.current_candle_key(symbol), self._ttl(symbol, candle.bar_time.date(), self.bars_ttl_seconds)
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
            keys.trend_key(symbol),
            keys.pattern_key(symbol),
            keys.pattern_events_key(symbol),
            keys.subscription_key(symbol),
        ):
            pipe.expire(key, ttl_seconds)
        await pipe.execute()

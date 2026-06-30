"""Async Redis repository for realtime quotes, bars, subscriptions, and heartbeat."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from finance_analysis.core.time import utc_isoformat
from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState


def _encode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return utc_isoformat(value) or ""
    return str(value)


def _mapping(value: Any) -> dict[str, str]:
    source = asdict(value) if hasattr(value, "__dataclass_fields__") else dict(value)
    return {key: _encode(item) for key, item in source.items()}


def _candle_json(candle: CandleState) -> str:
    return json.dumps(_mapping(candle), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class RealtimeStateRepository:
    """The only owner of realtime Redis keys and serialization rules."""

    def __init__(
        self,
        redis: Any,
        *,
        bar_limit: int = 420,
        quote_ttl_seconds: int = 2 * 86400,
        bars_ttl_seconds: int = 3 * 86400,
        removed_ttl_seconds: int = 2 * 3600,
    ) -> None:
        self.redis = redis
        self.bar_limit = max(1, min(int(bar_limit), 1000))
        self.quote_ttl_seconds = quote_ttl_seconds
        self.bars_ttl_seconds = bars_ttl_seconds
        self.removed_ttl_seconds = removed_ttl_seconds

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
        pipe.expire(keys.quote_key(quote.symbol), self.quote_ttl_seconds)
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

    @staticmethod
    def _quote_from_mapping(symbol: str, raw: Mapping[str, Any]) -> QuoteState:
        quote = QuoteState(symbol=str(raw.get("symbol") or symbol))
        quote.merge(
            {
                key: value
                for key, value in raw.items()
                if key not in {"symbol", "event_time", "received_at"} and value != ""
            },
            event_time=datetime.fromisoformat(str(raw["event_time"]).replace("Z", "+00:00")),
            received_at=datetime.fromisoformat(str(raw["received_at"]).replace("Z", "+00:00")),
        )
        return quote

    async def write_current_candle(self, candle: CandleState) -> None:
        pipe = self.redis.pipeline(transaction=False)
        pipe.hset(keys.current_candle_key(candle.symbol), mapping=_mapping(candle))
        pipe.expire(keys.current_candle_key(candle.symbol), self.bars_ttl_seconds)
        await pipe.execute()

    async def get_current_candle(self, symbol: str) -> CandleState | None:
        raw = await self.redis.hgetall(keys.current_candle_key(symbol))
        return CandleState.from_mapping(raw) if raw else None

    async def upsert_bars(self, symbol: str, bars: Iterable[CandleState]) -> None:
        await self.upsert_bars_batch({symbol: bars})

    async def upsert_bars_batch(
        self,
        bars_by_symbol: Mapping[str, Iterable[CandleState]],
    ) -> None:
        valid_by_symbol = {
            symbol: {
                self._bar_field(bar): bar
                for bar in bars
                if bar.symbol == symbol and bar.is_valid()
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
            for field, bar in valid.items():
                pipe.zadd(index_key, {field: bar.bar_time.timestamp()})
                pipe.hset(data_key, field, _candle_json(bar))
            pipe.expire(index_key, self.bars_ttl_seconds)
            pipe.expire(data_key, self.bars_ttl_seconds)
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
        fields = await self.redis.zrangebyscore(
            keys.bars_index_key(symbol), start.timestamp(), end.timestamp()
        )
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
    ) -> None:
        if not quotes and not current_candles:
            return
        pipe = self.redis.pipeline(transaction=False)
        for symbol, quote in quotes.items():
            pipe.hset(keys.quote_key(symbol), mapping=_mapping(quote))
            pipe.expire(keys.quote_key(symbol), self.quote_ttl_seconds)
        for symbol, candle in current_candles.items():
            pipe.hset(keys.current_candle_key(symbol), mapping=_mapping(candle))
            pipe.expire(keys.current_candle_key(symbol), self.bars_ttl_seconds)
        await pipe.execute()

    async def expire_symbol_cache(self, symbol: str, *, ttl_seconds: int | None = None) -> None:
        ttl_seconds = ttl_seconds or self.removed_ttl_seconds
        pipe = self.redis.pipeline(transaction=False)
        for key in (
            keys.quote_key(symbol),
            keys.current_candle_key(symbol),
            keys.bars_index_key(symbol),
            keys.bars_data_key(symbol),
            keys.subscription_key(symbol),
        ):
            pipe.expire(key, ttl_seconds)
        await pipe.execute()

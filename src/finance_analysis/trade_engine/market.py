# -*- coding: utf-8 -*-
"""Shared 5m cache and quote/bar fetch for Trade Engine only."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.holdings.cache import BARS_KEY  # pragma: allowlist secret
from finance_analysis.integrations.market_data.config import portfolio_risk_minute_providers  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import Adjustment, Market  # pragma: allowlist secret
from finance_analysis.integrations.market_data.normalizer import infer_market  # pragma: allowlist secret
from finance_analysis.integrations.market_data.service import MarketDataService  # pragma: allowlist secret
from finance_analysis.trade_engine.bars import (  # pragma: allowlist secret
    NormalizedBar,
    apply_volume_quality,
    dedupe_closed,
    latest_expected_closed,
    normalize_market_bar,
)
from finance_analysis.trade_engine.config import get_risk_policy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import DailyBar, QuoteView  # pragma: allowlist secret

logger = logging.getLogger(__name__)

FIVE_M_TTL = 6 * 60 * 60
US_COLD_START_PERIOD = "1mo"
US_REFRESH_PERIOD = "5d"


class MinuteBarCache:
    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    def key(self, provider: str, symbol: str, *, timeframe: str = "5m", session: str = "rth") -> str:
        return BARS_KEY.format(provider=provider, symbol=symbol, adjustment="raw") + f":{timeframe}:{session}"

    def load(self, provider: str, symbol: str) -> dict[str, Any] | None:
        raw = self.redis.get(self.key(provider, symbol))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def save(self, provider: str, symbol: str, payload: dict[str, Any]) -> None:
        self.redis.set(self.key(provider, symbol), json.dumps(payload), ex=FIVE_M_TTL)


class RiskMarketGateway:
    def __init__(
        self,
        *,
        market_data: MarketDataService | None = None,
        cache: MinuteBarCache | None = None,
        redis_client: Any = None,
        timeout_seconds: float | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        self.market_data = market_data or MarketDataService()
        if cache is None:
            from finance_analysis.holdings.service import redis_client as default_redis  # pragma: allowlist secret

            cache = MinuteBarCache(redis_client or default_redis())
        self.cache = cache
        policy = get_risk_policy()
        self.timeout_seconds = float(timeout_seconds or policy.five_minute_timeout_seconds)
        self.max_concurrency = int(max_concurrency or policy.max_symbol_concurrency)
        self.publish_buffer = timedelta(seconds=policy.publish_buffer_seconds)
        self.quote_max_age = timedelta(seconds=policy.quote_max_age_seconds)
        self.qualities: dict[str, dict[str, Any]] = {}
        self.degraded_symbols: list[str] = []

    def quotes(self, symbols: Iterable[str], *, now: datetime | None = None) -> dict[str, QuoteView]:
        current = now or utc_now()
        unique = tuple(dict.fromkeys(symbols))
        if not unique:
            return {}
        by_market: dict[Market, list[str]] = {}
        for symbol in unique:
            by_market.setdefault(infer_market(symbol), []).append(symbol)
        result: dict[str, QuoteView] = {}
        for _market, codes in by_market.items():
            batch = self.market_data.get_realtime_quotes(codes)
            for symbol in codes:
                quote = batch.data.get(symbol)
                if quote is None or quote.price is None:
                    result[symbol] = QuoteView(price=Decimal("0"), quote_as_of=None, valid=False)
                    continue
                quote_time = quote.quote_time
                if quote_time is None:
                    result[symbol] = QuoteView(
                        price=Decimal(str(quote.price)), quote_as_of=None, valid=False, stale=True
                    )
                    continue
                if quote_time > current + timedelta(seconds=5):
                    result[symbol] = QuoteView(
                        price=Decimal(str(quote.price)), quote_as_of=quote_time, valid=False, stale=False
                    )
                    continue
                stale = current - quote_time > self.quote_max_age
                result[symbol] = QuoteView(
                    price=Decimal(str(quote.price)),
                    quote_as_of=quote_time,
                    valid=quote.price > 0 and not stale,
                    stale=stale,
                )
        return result

    def daily_bars(
        self,
        symbols: Iterable[str],
        *,
        start: date,
        end: date,
        now: datetime | None = None,
    ) -> dict[str, list[DailyBar]]:
        del now
        unique = tuple(dict.fromkeys(symbols))
        if not unique:
            return {}
        try:
            result = self.market_data.get_daily_bars(
                unique,
                start,
                end,
                adjustment=Adjustment.FORWARD,
                source_policy="db_first",
            )
        except Exception:
            logger.exception("trade_engine daily bars failed")
            return {symbol: [] for symbol in unique}
        converted: dict[str, list[DailyBar]] = {}
        for symbol in unique:
            rows = []
            for item in result.data.get(symbol) or []:
                rows.append(
                    DailyBar(
                        trade_date=item.trade_date,
                        open=Decimal(str(item.open)),
                        high=Decimal(str(item.high)),
                        low=Decimal(str(item.low)),
                        close=Decimal(str(item.close)),
                        volume=int(item.volume or 0),
                    )
                )
            converted[symbol] = sorted(rows, key=lambda bar: bar.trade_date)
        return converted

    def cached_five_minute_bars(
        self,
        symbols: Iterable[str],
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        now: datetime | None = None,
    ) -> dict[str, list[NormalizedBar]]:
        current = now or utc_now()
        result: dict[str, list[NormalizedBar]] = {}
        for symbol in dict.fromkeys(symbols):
            market = infer_market(symbol)
            provider = portfolio_risk_minute_providers(market)[0]
            cached = self.cache.load(provider, symbol)
            bars = self._from_cache(cached, now=current) if cached else []
            result[symbol] = self._window(bars, start=start, end=end)
        return result

    def symbols_needing_refresh(self, symbols: Iterable[str], *, now: datetime | None = None) -> list[str]:
        current = now or utc_now()
        needed: list[str] = []
        for symbol in dict.fromkeys(symbols):
            market = infer_market(symbol)
            provider = portfolio_risk_minute_providers(market)[0]
            cached = self.cache.load(provider, symbol)
            bars = self._from_cache(cached, now=current) if cached else []
            initialized = bool(cached and cached.get("initialized"))
            latest_closed = max((bar.bar_end for bar in bars), default=None)
            expected = latest_expected_closed(market.value, current)
            if not bars or not initialized:
                needed.append(symbol)
                continue
            if expected is None:
                continue
            if latest_closed is not None and latest_closed >= expected:
                continue
            if current < expected + self.publish_buffer:
                continue
            needed.append(symbol)
        return needed

    def five_minute_bars(
        self,
        symbols: Iterable[str],
        *,
        start: datetime,
        end: datetime,
        now: datetime | None = None,
        refresh: bool = False,
        timeout_seconds: float | None = None,
        wait_refresh: bool = True,
    ) -> dict[str, list[NormalizedBar]]:
        current = now or utc_now()
        unique = tuple(dict.fromkeys(symbols))
        cached_map = self.cached_five_minute_bars(unique, start=start, end=end, now=current)
        needed = unique if refresh else tuple(self.symbols_needing_refresh(unique, now=current))
        if not needed or not wait_refresh:
            return cached_map
        fetched = self._refresh_symbols(
            needed, start=start, end=end, now=current, timeout_seconds=timeout_seconds
        )
        merged = dict(cached_map)
        merged.update(fetched)
        return {symbol: self._window(bars, start=start, end=end) for symbol, bars in merged.items()}

    def _refresh_symbols(
        self,
        symbols: Iterable[str],
        *,
        start: datetime,
        end: datetime,
        now: datetime,
        timeout_seconds: float | None,
    ) -> dict[str, list[NormalizedBar]]:
        timeout = self.timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        unique = list(dict.fromkeys(symbols))
        result: dict[str, list[NormalizedBar]] = {}
        degraded: list[str] = []
        write_ns = time.time_ns()
        workers = max(1, min(self.max_concurrency, len(unique) or 1))
        started = time.perf_counter()
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pr-5m")
        pending: dict[Any, str] = {}
        queue = list(unique)
        try:
            while queue or pending:
                remaining = timeout - (time.perf_counter() - started)
                if remaining <= 0:
                    degraded.extend(queue)
                    queue.clear()
                    if pending:
                        wait(list(pending), timeout=min(8.0, self.timeout_seconds))
                        for future, symbol in list(pending.items()):
                            if future.done():
                                try:
                                    payload = future.result()
                                    if payload is not None:
                                        result[symbol] = payload
                                    else:
                                        degraded.append(symbol)
                                except Exception:
                                    degraded.append(symbol)
                            else:
                                degraded.append(symbol)
                            pending.pop(future, None)
                    break
                while queue and len(pending) < workers:
                    symbol = queue.pop(0)
                    pending[executor.submit(self._refresh_one_symbol, symbol, start, end, now, write_ns)] = symbol
                done, _not_done = wait(list(pending), timeout=max(0.05, remaining), return_when=FIRST_COMPLETED)
                if not done:
                    continue
                for future in done:
                    symbol = pending.pop(future)
                    try:
                        payload = future.result()
                        if payload is None:
                            degraded.append(symbol)
                            cached = self.cache.load(portfolio_risk_minute_providers(infer_market(symbol))[0], symbol)
                            result[symbol] = self._from_cache(cached, now=now) if cached else []
                        else:
                            result[symbol] = payload
                    except Exception:
                        logger.exception("trade_engine 5m refresh failed symbol=%s", symbol)
                        degraded.append(symbol)
                        self._mark_stale(symbol)
                        cached = self.cache.load(portfolio_risk_minute_providers(infer_market(symbol))[0], symbol)
                        result[symbol] = self._from_cache(cached, now=now) if cached else []
        finally:
            executor.shutdown(wait=True, cancel_futures=False)
        for symbol in unique:
            if symbol not in result:
                cached = self.cache.load(portfolio_risk_minute_providers(infer_market(symbol))[0], symbol)
                result[symbol] = self._from_cache(cached, now=now) if cached else []
                if symbol not in degraded:
                    degraded.append(symbol)
                    self._mark_stale(symbol)
        self.degraded_symbols = list(dict.fromkeys(degraded))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "trade_engine 5m refresh elapsed_ms=%s symbols=%s degraded=%s",
            elapsed_ms,
            len(result),
            len(self.degraded_symbols),
        )
        return result

    def _refresh_one_symbol(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        now: datetime,
        write_ns: int,
    ) -> list[NormalizedBar] | None:
        market = infer_market(symbol)
        providers = portfolio_risk_minute_providers(market)
        provider = providers[0]
        previous_payload = self.cache.load(provider, symbol) or {}
        previous = self._from_cache(previous_payload, now=now)
        period = None
        if market is Market.US:
            period = US_COLD_START_PERIOD if not previous_payload.get("initialized") else US_REFRESH_PERIOD
        try:
            remote = self.market_data.get_minute_bars(
                [symbol], start, end, interval="5m", providers=providers, period=period
            )
        except Exception:
            logger.exception("trade_engine minute fetch failed symbol=%s", symbol)
            self._mark_stale(symbol)
            return previous
        if symbol in remote.failed_symbols or symbol in remote.missing_symbols:
            self._mark_stale(symbol)
            return previous
        market_bars = remote.data.get(symbol) or []
        if not market_bars:
            self._mark_stale(symbol)
            return previous
        normalized = []
        for item in market_bars:
            bar = normalize_market_bar(item, now=now)
            if bar is not None:
                normalized.append(bar)
        if not normalized:
            self._mark_stale(symbol)
            return previous
        closed = apply_volume_quality(dedupe_closed(_merge_bars(previous, normalized)))
        existing = self.cache.load(provider, symbol) or {}
        if int(existing.get("write_ns") or 0) > write_ns:
            return self._from_cache(existing, now=now)
        expected = latest_expected_closed(market.value, now)
        latest_closed = max((bar.bar_end for bar in closed), default=None)
        stale = bool(expected is not None and latest_closed is not None and latest_closed < expected)
        self.cache.save(
            provider,
            symbol,
            {
                "fetched_at": now.isoformat(),
                "write_ns": write_ns,
                "stale": stale,
                "initialized": True,
                "provider": provider,
                "timeframe": "5m",
                "session": "rth",
                "adjustment": "raw",
                "latest_expected_closed": None if expected is None else expected.isoformat(),
                "bars": [_bar_payload(bar) for bar in closed],
            },
        )
        self.qualities[symbol] = {
            "stale": stale,
            "status": "STALE" if stale else "OK",
            "latest_expected_closed": expected,
        }
        return closed

    def bar_quality(self, symbol: str, *, now: datetime) -> dict[str, Any]:
        if symbol in self.qualities:
            return self.qualities[symbol]
        market = infer_market(symbol)
        provider = portfolio_risk_minute_providers(market)[0]
        cached = self.cache.load(provider, symbol) or {}
        expected = latest_expected_closed(market.value, now)
        return {
            "stale": bool(cached.get("stale")),
            "status": "STALE" if cached.get("stale") else ("OK" if cached.get("initialized") else "UNAVAILABLE"),
            "latest_expected_closed": expected,
        }

    def _mark_stale(self, symbol: str) -> None:
        provider = portfolio_risk_minute_providers(infer_market(symbol))[0]
        cached = self.cache.load(provider, symbol)
        if not cached:
            return
        cached["stale"] = True
        self.cache.save(provider, symbol, cached)

    def _from_cache(self, payload: dict[str, Any] | None, *, now: datetime) -> list[NormalizedBar]:
        if not payload:
            return []
        bars = []
        for item in payload.get("bars") or []:
            trade_date = date.fromisoformat(str(item["trade_date"])[:10])
            bar = NormalizedBar(
                symbol=item["symbol"],
                market=item["market"],
                trade_date=trade_date,
                bar_start=datetime.fromisoformat(item["bar_start"]),
                bar_end=datetime.fromisoformat(item["bar_end"]),
                session_id=item["session_id"],
                open=Decimal(item["open"]),
                high=Decimal(item["high"]),
                low=Decimal(item["low"]),
                close=Decimal(item["close"]),
                volume=int(item["volume"]),
                amount=None if item.get("amount") is None else Decimal(item["amount"]),
                amount_quality=item["amount_quality"],
                volume_quality=item["volume_quality"],
                provider=item["provider"],
                closed=True,
                slot_key=item["slot_key"],
            )
            if now >= bar.bar_end:
                bars.append(bar)
        return apply_volume_quality(bars)

    def _window(
        self, bars: list[NormalizedBar], *, start: datetime | None, end: datetime | None
    ) -> list[NormalizedBar]:
        selected = bars
        if start is not None:
            selected = [bar for bar in selected if bar.bar_end >= start]
        if end is not None:
            selected = [bar for bar in selected if bar.bar_end <= end]
        return selected


def _merge_bars(previous: list[NormalizedBar], incoming: list[NormalizedBar]) -> list[NormalizedBar]:
    merged = {bar.bar_end: bar for bar in previous}
    merged.update({bar.bar_end: bar for bar in incoming})
    return [merged[key] for key in sorted(merged)]


def _bar_payload(bar: NormalizedBar) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "market": bar.market,
        "trade_date": bar.trade_date.isoformat(),
        "bar_start": bar.bar_start.isoformat(),
        "bar_end": bar.bar_end.isoformat(),
        "session_id": bar.session_id,
        "open": format(bar.open, "f"),
        "high": format(bar.high, "f"),
        "low": format(bar.low, "f"),
        "close": format(bar.close, "f"),
        "volume": bar.volume,
        "amount": None if bar.amount is None else format(bar.amount, "f"),
        "amount_quality": bar.amount_quality,
        "volume_quality": bar.volume_quality,
        "provider": bar.provider,
        "slot_key": bar.slot_key,
    }

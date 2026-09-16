"""Fuyao's public REST capabilities, normalized at the integration boundary.

Contract: https://fuyao.aicubes.cn/llms-full.txt. Prices are CNY, volume
is shares, percentages are percentage points, and timestamps are milliseconds.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import re
import math
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..config import get_data_provider_config
from ..models import (
    Adjustment,
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    IndexDailyBar,
    InstrumentInfo,
    InstrumentRequest,
    Market,
    MarketBar,
    MarketIndex,
    MarketQuote,
    MarketStats,
    QuoteRequest,
    SectorRankings,
)
from ..normalizer import canonical_symbol, infer_market
from ..request_budget import BudgetExhausted, check_budget, remaining_seconds
from ..validator import validate_bars, validate_quote

SHANGHAI = ZoneInfo("Asia/Shanghai")
INDEX_NAMES = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
}


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def timestamp(value: Any) -> datetime | None:
    value = number(value)
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc) if value is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def date_ms(day: date) -> int:
    return int(datetime.combine(day, time.min, SHANGHAI).timestamp() * 1000)


class FuyaoError(RuntimeError):
    """Sanitized transport or envelope failure; never includes payloads or keys."""


class FuyaoProvider:
    name = "fuyao"
    _shared_cache = {}
    _cache_lock = RLock()

    def __init__(self, *, api_key: str | None = None, timeout: float | None = None, transport=None):
        config = get_data_provider_config()
        self._api_key = api_key if api_key is not None else config.fuyao_api_key
        self.timeout = timeout if timeout is not None else config.fuyao_timeout_seconds
        self._transport = transport
        self._asset_types: dict[str, tuple[float, str]] = {}

    def cached(self, key, ttl, load):
        """Single-flight process-local cache shared by all adapters using this provider.

        Failed loads are never cached. Copies protect subsequent callers from mutation.
        Lock waiting consumes the same request budget as network I/O.
        """
        key = ((hash(self._api_key), self._transport), key)
        remaining = remaining_seconds()
        acquired = (
            self._cache_lock.acquire(timeout=max(0.0, remaining))
            if remaining is not None else self._cache_lock.acquire()
        )
        if not acquired:
            raise BudgetExhausted()
        try:
            now = monotonic()
            cached = self._shared_cache.get(key)
            if cached and cached[0] > now:
                return deepcopy(cached[1])
            check_budget()
            value = load()
            for expired in [k for k, v in self._shared_cache.items() if v[0] <= now]:
                del self._shared_cache[expired]
            if len(self._shared_cache) >= 512:
                self._shared_cache.pop(next(iter(self._shared_cache)))
            self._shared_cache[key] = (monotonic() + ttl, deepcopy(value))
            return value
        finally:
            self._cache_lock.release()

    def _get(self, path: str, **params) -> dict:
        check_budget()
        remaining = remaining_seconds()
        # Reserve time for all four HTTP phases. Never mutate the provider default.
        timeout = self.timeout if remaining is None else min(self.timeout, remaining / 4)
        if not self._api_key:
            raise FuyaoError("FUYAO_API_KEY is not configured")
        try:
            with httpx.Client(transport=self._transport, timeout=timeout) as client:
                response = client.get(
                    "https://fuyao.aicubes.cn" + path,
                    params=params,
                    headers={"X-api-key": self._api_key},
                )
                if response.status_code != 200:
                    raise FuyaoError(f"Fuyao HTTP {response.status_code}: {path}")
                envelope = response.json()
        except FuyaoError:
            raise
        except Exception as exc:
            raise FuyaoError(f"Fuyao {type(exc).__name__}: {path}") from None
        if not isinstance(envelope, dict) or envelope.get("code") != 0:
            code = envelope.get("code") if isinstance(envelope, dict) else None
            code = code if isinstance(code, int) else "invalid"
            raise FuyaoError(f"Fuyao error code={code}: {path}")
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise FuyaoError(f"Fuyao invalid data: {path}")
        return data

    @staticmethod
    def _items(data: dict) -> list[dict]:
        items = data.get("item")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise FuyaoError("Fuyao invalid item list")
        return items

    @staticmethod
    def _cn(market):
        if market != Market.CN:
            raise ValueError("Fuyao supports CN only")

    def _symbol(self, value: str) -> str:
        symbol = canonical_symbol(value)
        self._cn(infer_market(symbol))
        return symbol

    def _pages(self, path: str, **params) -> list[dict]:
        rows, seen = [], set()
        size = 1000
        for offset in range(0, 100000, size):
            data = self._get(path, limit=size, offset=offset, **params)
            page = self._items(data)
            keys = {row["thscode"] for row in page}
            if keys & seen or len(keys) != len(page):
                raise FuyaoError("Fuyao duplicate pagination records")
            seen.update(keys)
            rows.extend(page)
            total = data.get("total")
            if total is not None and offset + size >= int(total):
                if len(rows) != int(total):
                    raise FuyaoError("Fuyao incomplete directory")
                return rows
            if total is None and len(page) < size:
                return rows
        raise FuyaoError("Fuyao pagination exceeded bound")

    def _asset_type(self, symbol: str) -> str:
        cached = self._asset_types.get(symbol)
        if cached and monotonic() - cached[0] < 1800:
            return cached[1]
        data = self._get("/api/meta/tickers/search", q=symbol, limit=50)
        row = next((r for r in self._items(data) if r.get("thscode") == symbol), None)
        kind = row.get("asset_type") if row else None
        if kind not in {"a-share", "a-share-index", "fund-etf"}:
            raise FuyaoError("Fuyao missing or unsupported instrument type")
        if len(self._asset_types) >= 10000:
            self._asset_types.clear()
        self._asset_types[symbol] = (monotonic(), kind)
        return kind

    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult:
        if request.adjustment is not Adjustment.FORWARD:
            raise ValueError("Fuyao daily bars require forward adjustment")
        result = BatchBarResult()
        for value in request.symbols:
            symbol = self._symbol(value)
            try:
                kind = self._asset_type(symbol)
                path = {
                    "a-share": "/api/a-share/prices/historical",
                    "a-share-index": "/api/a-share-index/prices/historical",
                    "fund-etf": "/api/fund/market/historical",
                }[kind]
                rows = []
                start = request.start_date
                while start <= request.end_date:
                    end = min(request.end_date, start + timedelta(days=1825 if kind == "fund-etf" else 3650))
                    data = self._get(
                        path,
                        thscode=symbol,
                        interval="1d",
                        start=date_ms(start),
                        end=date_ms(end),
                        **({"adjust": "forward"} if kind == "a-share" else {}),
                    )
                    expected_adjust = "forward" if kind == "a-share" else None
                    if data.get("adjust", expected_adjust) != expected_adjust:
                        raise FuyaoError("Fuyao returned unexpected adjustment")
                    if data.get("thscode", symbol) != symbol or data.get("interval", "1d") != "1d":
                        raise FuyaoError("Fuyao unexpected historical identity")
                    for row in self._items(data):
                        day = timestamp(row["date_ms"]).astimezone(SHANGHAI).date()
                        if start <= day <= end:
                            rows.append(
                                MarketBar(
                                    symbol,
                                    Market.CN,
                                    "1d",
                                    day,
                                    None,
                                    float(row["open_price"]),
                                    float(row["high_price"]),
                                    float(row["low_price"]),
                                    float(row["close_price"]),
                                    int(row["volume"]),
                                    number(row.get("turnover")),
                                    "CNY",
                                    Adjustment.FORWARD,
                                    self.name,
                                )
                            )
                    start = end + timedelta(days=1)
                if len({bar.trade_date for bar in rows}) != len(rows):
                    raise FuyaoError("Fuyao duplicate daily dates")
                bars = validate_bars(sorted(rows, key=lambda bar: bar.trade_date))
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
                result.request_errors[symbol] = str(exc)
        return result

    def _quote(self, row: dict, as_of: Any, name: str = "") -> MarketQuote:
        return validate_quote(
            MarketQuote(
                symbol=self._symbol(row["thscode"]),
                market=Market.CN,
                provider=self.name,
                currency="CNY",
                name=name,
                price=number(row.get("last_price")),
                change_pct=number(row.get("price_change_ratio_pct")),
                change_amount=number(row.get("price_change")),
                volume=int(row["volume"]) if number(row.get("volume")) is not None else None,
                amount=number(row.get("turnover")),
                open_price=number(row.get("open_price")),
                high=number(row.get("high_price")),
                low=number(row.get("low_price")),
                pre_close=number(row.get("prev_price")),
                quote_time=timestamp(as_of),
                amplitude=number(row.get("price_amplitude_ratio_pct")),
                turnover_rate=number(row.get("turnover_ratio_pct")),
            )
        )

    def fetch_quotes(self, request: QuoteRequest) -> BatchQuoteResult:
        symbols = tuple(self._symbol(value) for value in request.symbols)
        result = BatchQuoteResult()
        groups = {"a-share": [], "a-share-index": [], "fund-etf": []}
        for symbol in symbols:
            try:
                groups[self._asset_type(symbol)].append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        for kind, values in groups.items():
            size = 1 if kind == "fund-etf" else 100
            path = {
                "a-share": "/api/a-share/prices/snapshot",
                "a-share-index": "/api/a-share-index/prices/snapshot",
                "fund-etf": "/api/fund/market/snapshot",
            }[kind]
            for offset in range(0, len(values), size):
                batch = values[offset : offset + size]
                params = {"thscode": batch[0]} if size == 1 else {"thscodes": ",".join(batch)}
                try:
                    data = self._get(path, **params)
                    for row in self._items(data):
                        symbol = row.get("thscode")
                        if symbol not in batch:
                            raise FuyaoError("Fuyao unexpected snapshot symbol")
                        try:
                            result.data[symbol] = self._quote(row, data.get("timestamp"))
                            result.providers_used[symbol] = self.name
                        except Exception as exc:
                            result.failed_symbols[symbol] = str(exc)
                except Exception as exc:
                    result.failed_symbols.update({symbol: str(exc) for symbol in batch})
        result.missing_symbols = [s for s in symbols if s not in result.data and s not in result.failed_symbols]
        return result

    def fetch_market_snapshot(self, market: Market) -> BatchQuoteResult:
        self._cn(market)
        # Directory names are required by review/ST filters, but absent in prices.
        names = {row["code"]: row["name"] for row in self.fetch_instruments("CN")}
        result = BatchQuoteResult()
        size, seen, total = 1000, set(), None
        for offset in range(0, 100000, size):
            data = self._get("/api/a-share/prices/snapshot", limit=size, offset=offset)
            current_total = int(data["total"])
            if total is not None and total != current_total:
                raise FuyaoError("Fuyao snapshot directory changed during pagination")
            total = current_total
            for row in self._items(data):
                symbol = self._symbol(row["thscode"])
                if symbol in seen:
                    raise FuyaoError("Fuyao duplicate snapshot page")
                seen.add(symbol)
                # Suspended/not-yet-trading rows have no price and no activity.
                # Exclude them from breadth rather than inventing a flat quote.
                if number(row.get("last_price")) is None and all(
                    number(row.get(field)) in (None, 0) for field in ("volume", "turnover", "price_change")
                ):
                    result.missing_symbols.append(symbol)
                    continue
                try:
                    result.data[symbol] = self._quote(row, data.get("timestamp"), names.get(symbol, ""))
                    result.providers_used[symbol] = self.name
                except Exception as exc:
                    result.failed_symbols[symbol] = str(exc)
            if offset + size >= total:
                if len(seen) < total:
                    result.failed_symbols["CN"] = "Fuyao incomplete full-market snapshot"
                return result
        raise FuyaoError("Fuyao snapshot pagination exceeded bound")

    def get_indices(self, market: Market) -> list[MarketIndex]:
        self._cn(market)
        data = self._get("/api/a-share-index/prices/snapshot", thscodes=",".join(INDEX_NAMES))
        result = []
        for row in self._items(data):
            quote = self._quote(row, data.get("timestamp"), INDEX_NAMES.get(row["thscode"], ""))
            if quote.change_pct is None or quote.change_amount is None:
                raise FuyaoError("Fuyao index changes missing")
            result.append(
                MarketIndex(
                    quote.symbol,
                    quote.name,
                    market,
                    self.name,
                    quote.price,
                    quote.change_amount,
                    quote.change_pct,
                    quote.open_price,
                    quote.high,
                    quote.low,
                    quote.pre_close,
                    quote.volume,
                    quote.amount,
                )
            )
        return result

    def get_market_stats(self, market: Market) -> MarketStats:
        snapshot = self.fetch_market_snapshot(market)
        quotes = list(snapshot.data.values())
        if not quotes or snapshot.failed_symbols or any(q.change_pct is None for q in quotes):
            raise FuyaoError("Fuyao incomplete breadth snapshot")
        days = {q.quote_time.astimezone(SHANGHAI).date() for q in quotes if q.quote_time}
        if len(days) != 1 or any(q.quote_time is None for q in quotes):
            raise FuyaoError("Fuyao inconsistent snapshot dates")
        counts = []
        for pool in ("limit-up-pool", "limit-down-pool"):
            data = self._get(f"/api/a-share/special-data/{pool}", date_ms=date_ms(next(iter(days))), page=1, size=1)
            counts.append(int(data["pagination"]["total"]))
        return MarketStats(
            market,
            self.name,
            sum(q.change_pct > 0 for q in quotes),
            sum(q.change_pct < 0 for q in quotes),
            sum(q.change_pct == 0 for q in quotes),
            *counts,
            sum(q.amount for q in quotes) if all(q.amount is not None for q in quotes) else None,
        )

    def get_sector_rankings(self, market: Market) -> SectorRankings:
        self._cn(market)
        return self.cached("sector_rankings:CN", 300, lambda: self._load_sector_rankings(market))

    def _load_sector_rankings(self, market: Market) -> SectorRankings:
        names = {}
        for tag in ("industry", "cn_concept"):
            data = self._get("/api/a-share-index/catalog/ths-index-list", tag=tag)
            names.update({row["thscode"]: row["name"] for row in self._items(data)})
        ranks = []
        seen = set()
        symbols = list(names)
        for offset in range(0, len(symbols), 100):
            data = self._get("/api/a-share-index/prices/snapshot", thscodes=",".join(symbols[offset : offset + 100]))
            for row in self._items(data):
                change = number(row.get("price_change_ratio_pct"))
                if change is None or row["thscode"] not in names:
                    raise FuyaoError("Fuyao invalid sector snapshot")
                if row["thscode"] in seen:
                    raise FuyaoError("Fuyao duplicate sector snapshot")
                seen.add(row["thscode"])
                ranks.append({"name": names[row["thscode"]], "change_pct": change})
        if not ranks or seen != set(names):
            raise FuyaoError("Fuyao incomplete sector snapshot")
        return SectorRankings(
            market,
            self.name,
            sorted(ranks, key=lambda r: -r["change_pct"]),
            sorted(ranks, key=lambda r: r["change_pct"]),
        )

    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult:
        result = BatchInstrumentResult()
        kinds = {"a-share": "stock", "fund-etf": "etf", "a-share-index": "index"}
        for value in request.symbols:
            symbol = self._symbol(value)
            try:
                data = self._get("/api/meta/tickers/search", q=symbol, limit=50)
                row = next((r for r in self._items(data) if r.get("thscode") == symbol), None)
                if row and row.get("name"):
                    result.data[symbol] = InstrumentInfo(
                        symbol,
                        Market.CN,
                        row["name"],
                        self.name,
                        "CNY",
                        symbol.rsplit(".", 1)[1],
                        kinds.get(row.get("asset_type")),
                    )
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def fetch_instruments(self, market: str) -> list[dict]:
        self._cn(Market(market))
        return [self._instrument_record(row) for row in self._pages("/api/meta/tickers/list", asset_type="a-share")]

    def _instrument_record(self, row: dict) -> dict:
        symbol = self._symbol(row["thscode"])
        return {
            "code": symbol,
            "name": row["name"],
            "market": "CN",
            "currency": "CNY",
            "native_code": symbol.rsplit(".", 1)[0],
            "instrument_type": "STOCK",
            "source": "FUYAO",
        }

    def fetch_index_members(self, index_code: str) -> list[dict]:
        data = self._get("/api/a-share-index/constituents/ths-stock-list", thscode=self._symbol(index_code))
        return [self._instrument_record(row) for row in self._items(data)]

    def _members(self, path, pattern, **params):
        data = self._get("/api/a-share-index/" + path, **params)
        rows = self._items(data)
        if not rows or any(
            not isinstance(r, dict)
            or not re.fullmatch(pattern, str(r.get("thscode", "")))
            or not str(r.get("name", "")).strip()
            for r in rows
        ):
            raise FuyaoError("Fuyao empty or invalid reference list")
        if len({r["thscode"] for r in rows}) != len(rows):
            raise FuyaoError("Fuyao duplicate reference codes")
        return [{"thscode": r["thscode"], "name": r["name"]} for r in rows]

    def get_industry_catalog(self):
        return self._members("catalog/ths-index-list", r"\d{6}\.TI", tag="industry")

    def get_index_constituents(self, code):
        self._validate_index(code)
        return self._members("constituents/ths-stock-list", r"\d{6}\.(SH|SZ|BJ)", thscode=code)

    def get_index_history(self, code, start, end):
        self._validate_index(code)
        data = self._get(
            "/api/a-share-index/prices/historical",
            thscode=code,
            interval="1d",
            start=int(datetime.combine(start, time.min, SHANGHAI).timestamp() * 1000),
            end=int(datetime.combine(end + timedelta(days=1), time.min, SHANGHAI).timestamp() * 1000) - 1,
        )
        try:
            bars = [
                IndexDailyBar(
                    trade_date=datetime.fromtimestamp(r["date_ms"] / 1000, SHANGHAI).date(),
                    close=float(r["close_price"]),
                    amount=float(r["turnover"]),
                    open=float(r["open_price"]),
                    high=float(r["high_price"]),
                    low=float(r["low_price"]),
                    volume=float(r["volume"]),
                )
                for r in self._items(data)
            ]
            timestamp = datetime.fromtimestamp(data["timestamp"] / 1000, timezone.utc)
        except (ValueError, KeyError, TypeError, OverflowError):
            raise FuyaoError("Fuyao invalid historical bars") from None
        return [b for b in bars if start <= b.trade_date <= end], timestamp

    @staticmethod
    def _validate_index(code):
        if not re.fullmatch(r"\d{6}\.(TI|SH|SZ)", code):
            raise ValueError("Fuyao supports A-share indices only")

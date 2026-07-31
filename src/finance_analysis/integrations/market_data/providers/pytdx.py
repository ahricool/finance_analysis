"""PyTDX provider with SDK host discovery and a reused connection."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from threading import RLock
from typing import Any, Iterable

import pandas as pd

from finance_analysis.integrations.market_data.models import (
    Adjustment,
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentInfo,
    InstrumentRequest,
    Market,
    MarketIndex,
    MinuteBarsRequest,
    QuoteRequest,
)
from finance_analysis.integrations.market_data.normalizer import (
    bars_from_frame,
    canonical_symbol,
    currency_for_market,
    infer_market,
    quote_from_value,
)

logger = logging.getLogger(__name__)

_BAR_CATEGORIES = {"1m": 8, "5m": 0, "15m": 1, "30m": 2, "60m": 3, "1d": 9}
_CN_INDICES = (
    ("000001.SH", "上证指数"),
    ("399001.SZ", "深证成指"),
    ("399006.SZ", "创业板指"),
    ("000688.SH", "科创50"),
    ("000016.SH", "上证50"),
    ("000300.SH", "沪深300"),
)


def _configured_hosts() -> list[tuple[str, int]]:
    entries = os.getenv("PYTDX_SERVERS", "").strip()
    if entries:
        hosts: list[tuple[str, int]] = []
        for entry in entries.split(","):
            host, separator, port = entry.strip().rpartition(":")
            if separator and host and port.isdigit():
                hosts.append((host, int(port)))
        if hosts:
            return hosts
    host = os.getenv("PYTDX_HOST", "").strip()
    port = os.getenv("PYTDX_PORT", "").strip()
    return [(host, int(port))] if host and port.isdigit() else []


def _sdk_hosts() -> list[tuple[str, int]]:
    try:
        from pytdx.config.hosts import hq_hosts
    except ImportError:
        return []
    discovered: list[tuple[str, int]] = []
    for item in hq_hosts:
        if isinstance(item, (tuple, list)) and len(item) >= 3:
            discovered.append((str(item[1]), int(item[2])))
        elif isinstance(item, dict) and item.get("ip") and item.get("port"):
            discovered.append((str(item["ip"]), int(item["port"])))
    return list(dict.fromkeys(discovered))


class PyTDXProvider:
    name = "pytdx"
    SECURITY_LIST_PAGE_SIZE = 1000

    def __init__(self, hosts: Iterable[tuple[str, int]] | None = None, *, api: Any = None) -> None:
        self._hosts = list(hosts or _configured_hosts() or _sdk_hosts())
        self._api = api
        self._connected_host: tuple[str, int] | None = ("injected", 0) if api is not None else None
        self._lock = RLock()
        self._stock_names: dict[str, str] | None = None

    @staticmethod
    def _provider_identity(symbol: str) -> tuple[int, str]:
        canonical = canonical_symbol(symbol, Market.CN)
        code, exchange = canonical.split(".")
        if exchange == "BJ":
            raise ValueError(f"PyTDX does not support Beijing Exchange symbol {symbol}")
        return (1 if exchange == "SH" else 0), code

    def _new_api(self):
        from pytdx.hq import TdxHq_API

        return TdxHq_API(heartbeat=True, auto_retry=True, raise_exception=True)

    def _connect_locked(self):
        if self._api is not None and self._connected_host is not None:
            return self._api
        if not self._hosts:
            raise ConnectionError("PyTDX SDK did not provide any quote servers")
        last_error: Exception | None = None
        for host, port in self._hosts:
            api = self._api or self._new_api()
            try:
                if api.connect(host, port, time_out=5):
                    self._api = api
                    self._connected_host = (host, port)
                    return api
            except Exception as exc:
                last_error = exc
            try:
                api.disconnect()
            except Exception:
                pass
            self._api = None
        raise ConnectionError(f"PyTDX could not connect to any discovered server: {last_error or 'unknown'}")

    def _call(self, callback):
        with self._lock:
            api = self._connect_locked()
            try:
                return callback(api)
            except Exception:
                try:
                    api.disconnect()
                except Exception:
                    pass
                self._api = None
                self._connected_host = None
                api = self._connect_locked()
                return callback(api)

    def close(self) -> None:
        with self._lock:
            api, self._api = self._api, None
            self._connected_host = None
        if api is not None:
            try:
                api.disconnect()
            except Exception:
                logger.debug("PyTDX disconnect failed", exc_info=True)

    def _bars(self, symbol: str, category: int, start: datetime, end: datetime) -> pd.DataFrame:
        market, code = self._provider_identity(symbol)

        def fetch(api):
            chunks: list[pd.DataFrame] = []
            offset = 0
            while offset < 8000:
                raw = api.get_security_bars(category, market, code, offset, 800) or []
                if not raw:
                    break
                frame = api.to_df(raw)
                chunks.append(frame)
                timestamps = pd.to_datetime(frame["datetime"], errors="coerce")
                if timestamps.min().to_pydatetime().replace(tzinfo=None) <= start.replace(tzinfo=None):
                    break
                if len(raw) < 800:
                    break
                offset += len(raw)
            if not chunks:
                return pd.DataFrame()
            frame = pd.concat(chunks, ignore_index=True)
            frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
            naive_start, naive_end = start.replace(tzinfo=None), end.replace(tzinfo=None)
            return frame[(frame["datetime"] >= naive_start) & (frame["datetime"] <= naive_end)]

        return self._call(fetch)

    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult:
        if request.adjustment is not Adjustment.RAW:
            raise ValueError("PyTDX only returns raw bars")
        result = BatchBarResult()
        start = datetime.combine(request.start_date, datetime.min.time())
        end = datetime.combine(request.end_date, datetime.max.time())
        for requested_symbol in request.symbols:
            symbol = canonical_symbol(requested_symbol, Market.CN)
            try:
                frame = self._bars(symbol, _BAR_CATEGORIES["1d"], start, end)
                bars = bars_from_frame(
                    frame.rename(columns={"datetime": "date", "vol": "volume"}),
                    symbol=symbol,
                    provider=self.name,
                    interval="1d",
                    adjustment=Adjustment.RAW,
                    volume_multiplier=100,
                )
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def fetch_minute_bars(self, request: MinuteBarsRequest) -> BatchBarResult:
        category = _BAR_CATEGORIES.get(request.interval)
        if category is None:
            raise ValueError(f"PyTDX does not support interval={request.interval}")
        result = BatchBarResult()
        for requested_symbol in request.symbols:
            symbol = canonical_symbol(requested_symbol, Market.CN)
            try:
                frame = self._bars(symbol, category, request.start_time, request.end_time)
                bars = bars_from_frame(
                    frame.rename(columns={"datetime": "bar_time", "vol": "volume"}),
                    symbol=symbol,
                    provider=self.name,
                    interval=request.interval,
                    volume_multiplier=100,
                )
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def fetch_quotes(self, request: QuoteRequest) -> BatchQuoteResult:
        result = BatchQuoteResult()
        identities: list[tuple[int, str]] = []
        canonical: list[str] = []
        for value in request.symbols:
            symbol = canonical_symbol(value, Market.CN)
            canonical.append(symbol)
            identities.append(self._provider_identity(symbol))
        try:
            rows = self._call(lambda api: api.get_security_quotes(identities) or [])
        except Exception as exc:
            return BatchQuoteResult(failed_symbols={symbol: str(exc) for symbol in canonical})
        by_identity = {(int(row.get("market", -1)), str(row.get("code", ""))): row for row in rows}
        for symbol, identity in zip(canonical, identities):
            row = by_identity.get(identity)
            if row is None:
                result.missing_symbols.append(symbol)
                continue
            value = {
                "price": row.get("price"),
                "pre_close": row.get("last_close"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "volume": (row.get("vol") or 0) * 100,
                "amount": row.get("amount"),
                "name": (self._stock_names or {}).get(identity[1], ""),
            }
            quote = quote_from_value(value, symbol=symbol, provider=self.name)
            if quote is None:
                result.missing_symbols.append(symbol)
            else:
                result.data[symbol] = quote
                result.providers_used[symbol] = self.name
        return result

    def _load_stock_names(self) -> dict[str, str]:
        if self._stock_names is not None:
            return self._stock_names

        def fetch(api):
            names: dict[str, str] = {}
            for market in (0, 1):
                offset = 0
                while True:
                    rows = api.get_security_list(market, offset) or []
                    for row in rows:
                        if row.get("code") and row.get("name"):
                            names[str(row["code"])] = str(row["name"]).strip()
                    if len(rows) < self.SECURITY_LIST_PAGE_SIZE:
                        break
                    offset += len(rows)
            return names

        self._stock_names = self._call(fetch)
        return self._stock_names

    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult:
        result = BatchInstrumentResult()
        try:
            names = self._load_stock_names()
        except Exception as exc:
            return BatchInstrumentResult(failed_symbols={symbol: str(exc) for symbol in request.symbols})
        for value in request.symbols:
            symbol = canonical_symbol(value, Market.CN)
            _, code = self._provider_identity(symbol)
            name = names.get(code, "")
            if not name:
                result.missing_symbols.append(symbol)
                continue
            result.data[symbol] = InstrumentInfo(
                symbol=symbol,
                market=Market.CN,
                name=name,
                provider=self.name,
                currency=currency_for_market(Market.CN),
                exchange=symbol.rsplit(".", 1)[1],
                instrument_type="stock",
            )
            result.providers_used[symbol] = self.name
        return result

    def fetch_market_snapshot(self, market: Market) -> BatchQuoteResult:
        if market is not Market.CN:
            raise ValueError("PyTDX full-market snapshot supports CN only")
        names = self._load_stock_names()
        symbols = [canonical_symbol(code, Market.CN) for code in names if len(code) == 6 and code[0] in "036"]
        combined = BatchQuoteResult()
        for offset in range(0, len(symbols), 80):
            batch = self.fetch_quotes(QuoteRequest(tuple(symbols[offset : offset + 80])))
            combined.data.update(batch.data)
            combined.failed_symbols.update(batch.failed_symbols)
            combined.missing_symbols.extend(batch.missing_symbols)
            combined.providers_used.update(batch.providers_used)
        return combined

    def get_indices(self, market: Market) -> list[MarketIndex]:
        if market is not Market.CN:
            return []
        quotes = self.fetch_quotes(QuoteRequest(tuple(symbol for symbol, _ in _CN_INDICES)))
        indices: list[MarketIndex] = []
        for symbol, name in _CN_INDICES:
            quote = quotes.data.get(symbol)
            if quote is None or quote.price is None:
                continue
            indices.append(
                MarketIndex(
                    symbol=symbol,
                    name=name,
                    market=Market.CN,
                    provider=self.name,
                    price=quote.price,
                    change=quote.change_amount or 0.0,
                    change_pct=quote.change_pct or 0.0,
                    volume=quote.volume,
                    amount=quote.amount,
                )
            )
        return indices


__all__ = ["PyTDXProvider"]

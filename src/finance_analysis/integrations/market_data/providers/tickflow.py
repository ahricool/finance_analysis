"""TickFlow free-tier provider for forward-adjusted daily bars and metadata."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import RLock
from typing import Any, Mapping

import pandas as pd

from finance_analysis.integrations.market_data.models import (
    Adjustment,
    BatchBarResult,
    BatchInstrumentResult,
    DailyBarsRequest,
    InstrumentInfo,
    InstrumentRequest,
)
from finance_analysis.integrations.market_data.normalizer import (
    bars_from_frame,
    canonical_symbol,
    currency_for_market,
    infer_market,
    local_midnight_timestamp_ms,
)

TICKFLOW_MAX_KLINE_COUNT = 10_000


class TickFlowFreeProvider:
    """Anonymous free API client; paid realtime/minute endpoints are intentionally absent."""

    name = "tickflow"

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        batch_size: int = 100,
        max_workers: int = 5,
        client: Any = None,
    ) -> None:
        if not 1 <= int(batch_size) <= 100:
            raise ValueError("TickFlow batch_size must be between 1 and 100")
        if int(max_workers) < 1:
            raise ValueError("TickFlow max_workers must be at least 1")
        self.timeout = timeout
        self.batch_size = int(batch_size)
        self.max_workers = int(max_workers)
        self._client = client
        self._client_lock = RLock()

    def _get_client(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    from tickflow import TickFlow

                    self._client = TickFlow.free(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        with self._client_lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()

    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult:
        if request.adjustment is not Adjustment.FORWARD:
            raise ValueError("TickFlow daily storage reads require adjustment='forward'")
        symbols = tuple(canonical_symbol(symbol) for symbol in request.symbols)
        result = BatchBarResult()
        frames = {}
        # The SDK's multi-chunk helper swallows exceptions. Keep its actual
        # batch download, but submit single HTTP-sized chunks ourselves so a
        # failed chunk cannot masquerade as a normal empty response.
        chunks = [symbols[i : i + self.batch_size] for i in range(0, len(symbols), self.batch_size)]
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            pending = {
                pool.submit(self._fetch_frames, chunk, request.start_date, request.end_date, adjust="forward"): chunk
                for chunk in chunks
            }
            for future in as_completed(pending):
                chunk = pending[future]
                try:
                    fetched = future.result()
                    if not isinstance(fetched, Mapping):
                        raise ValueError("unexpected TickFlow batch response")
                    frames.update(fetched)
                except Exception as exc:
                    reason = str(exc) or type(exc).__name__
                    result.failed_symbols.update({symbol: reason for symbol in chunk})
                    result.request_errors.update({symbol: reason for symbol in chunk})
        for symbol in symbols:
            if symbol in result.failed_symbols:
                continue
            frame = frames.get(symbol, pd.DataFrame())
            multiplier = 100 if infer_market(symbol).value == "CN" else 1
            bars = bars_from_frame(
                frame,
                symbol=symbol,
                provider=self.name,
                interval="1d",
                adjustment=Adjustment.FORWARD,
                volume_multiplier=multiplier,
            )
            bars = [bar for bar in bars if request.start_date <= bar.trade_date <= request.end_date]
            if bars:
                result.data[symbol] = bars
                result.providers_used[symbol] = self.name
            else:
                result.missing_symbols.append(symbol)
        return result

    def _fetch_frames(self, symbols, start_date, end_date, *, adjust: str):
        return self._get_client().klines.batch(
            list(symbols),
            period="1d",
            count=TICKFLOW_MAX_KLINE_COUNT,
            start_time=min(local_midnight_timestamp_ms(start_date, infer_market(symbol)) for symbol in symbols),
            end_time=max(local_midnight_timestamp_ms(end_date, infer_market(symbol)) for symbol in symbols),
            adjust=adjust,
            as_dataframe=True,
            show_progress=False,
            batch_size=self.batch_size,
            max_workers=self.max_workers,
        )

    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult:
        symbols = tuple(canonical_symbol(symbol) for symbol in request.symbols)
        result = BatchInstrumentResult()
        try:
            instruments = self._get_client().instruments.batch(list(symbols))
        except Exception as exc:
            return BatchInstrumentResult(failed_symbols={symbol: str(exc) for symbol in symbols})
        by_symbol = {str(item.get("symbol", "")).upper(): item for item in instruments}
        for symbol in symbols:
            item = by_symbol.get(symbol)
            if not item or not str(item.get("name") or "").strip():
                result.missing_symbols.append(symbol)
                continue
            market = infer_market(symbol)
            result.data[symbol] = InstrumentInfo(
                symbol=symbol,
                market=market,
                name=str(item["name"]).strip(),
                provider=self.name,
                currency=currency_for_market(market),
                exchange=str(item.get("exchange") or "") or None,
                instrument_type=str(item.get("type") or "") or None,
            )
            result.providers_used[symbol] = self.name
        return result

    def fetch_instruments(self, market: str) -> list[dict[str, Any]]:
        """Fetch the current security directory, excluding unsupported products."""
        normalized = str(getattr(market, "value", market)).upper()
        exchanges = {"CN": ("SH", "SZ", "BJ"), "HK": ("HK",), "US": ("US",)}.get(normalized)
        if exchanges is None:
            raise ValueError(f"Unsupported instrument market: {market}")
        records: dict[str, dict[str, Any]] = {}
        for exchange in exchanges:
            items = self._get_client().exchanges.get_instruments(exchange) or []
            if not items:
                raise ValueError(f"TickFlow returned an empty instrument directory for exchange={exchange}")
            for item in items:
                provider_type = str(item.get("type") or "").lower()
                if provider_type not in {"stock", "etf", "index"}:
                    continue
                raw = str(item.get("symbol") or item.get("code") or "").upper()
                native = raw.rsplit(".", 1)[0]
                code = canonical_symbol(raw or native, normalized)
                ext = item.get("ext") if isinstance(item.get("ext"), Mapping) else {}
                listing_date = pd.to_datetime(ext.get("listing_date"), errors="coerce")
                records[code] = {
                    "market": normalized,
                    "code": code,
                    "native_code": native,
                    "name": str(item.get("name") or code),
                    "instrument_type": provider_type.upper(),
                    "currency": currency_for_market(normalized),
                    "listing_date": None if pd.isna(listing_date) else listing_date.date(),
                    "listing_status": "ACTIVE",
                    "source": "TICKFLOW",
                    "metadata": {"exchange": exchange, "provider_type": provider_type, "ext": dict(ext)},
                }
        return list(records.values())


__all__ = ["TickFlowFreeProvider"]

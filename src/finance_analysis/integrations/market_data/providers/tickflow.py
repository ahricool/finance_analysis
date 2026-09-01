"""TickFlow free-tier provider for forward-adjusted daily bars and metadata."""

from __future__ import annotations

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
        try:
            frames = self._fetch_frames(symbols, request.start_date, request.end_date, adjust="forward")
        except Exception as exc:
            return BatchBarResult(failed_symbols={symbol: str(exc) for symbol in symbols})
        if not isinstance(frames, Mapping):
            return BatchBarResult(failed_symbols={symbol: "unexpected TickFlow batch response" for symbol in symbols})
        for symbol in symbols:
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
            ext = item.get("ext") or {}
            result.data[symbol] = InstrumentInfo(
                symbol=symbol,
                market=market,
                name=str(item["name"]).strip(),
                provider=self.name,
                currency=currency_for_market(market),
                exchange=str(item.get("exchange") or "") or None,
                instrument_type=str(item.get("type") or "") or None,
                lot_size=int(ext["lot_size"]) if ext.get("lot_size") else None,
            )
            result.providers_used[symbol] = self.name
        return result


__all__ = ["TickFlowFreeProvider"]

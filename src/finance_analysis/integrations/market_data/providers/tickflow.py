"""TickFlow free-tier provider for raw bars, derived adjustment factors, and metadata."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Mapping

import pandas as pd

from finance_analysis.integrations.market_data.models import (
    Adjustment,
    AdjustmentFactor,
    AdjustmentRequest,
    AdjustmentResult,
    BatchBarResult,
    BatchInstrumentResult,
    DailyBarsRequest,
    InstrumentInfo,
    InstrumentRequest,
)
from finance_analysis.integrations.market_data.normalizer import (
    MARKET_TIMEZONES,
    bars_from_frame,
    canonical_symbol,
    currency_for_market,
    infer_market,
    local_midnight_timestamp_ms,
)

TICKFLOW_MAX_KLINE_COUNT = 10_000
TICKFLOW_FACTOR_REL_TOLERANCE = 1e-9
TICKFLOW_LATEST_FACTOR_LOOKBACK_DAYS = 14
PRICE_FIELDS = ("open", "high", "low", "close")


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
        if request.adjustment is not Adjustment.RAW:
            raise ValueError("TickFlow storage reads must explicitly use adjustment='raw'")
        symbols = tuple(canonical_symbol(symbol) for symbol in request.symbols)
        result = BatchBarResult()
        try:
            frames = self._fetch_frames(symbols, request.start_date, request.end_date, adjust="none")
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
                adjustment=Adjustment.RAW,
                volume_multiplier=multiplier,
            )
            bars = [bar for bar in bars if request.start_date <= bar.trade_date <= request.end_date]
            if bars:
                result.data[symbol] = bars
                result.providers_used[symbol] = self.name
            else:
                result.missing_symbols.append(symbol)
        return result

    def get_adjustment_factors(self, request: AdjustmentRequest) -> AdjustmentResult:
        """Derive canonical daily factors from TickFlow raw and forward-adjusted bars."""
        symbols = tuple(canonical_symbol(symbol) for symbol in request.symbols)
        result = AdjustmentResult()
        try:
            raw_frames = self._fetch_frames(symbols, request.start_date, request.end_date, adjust="none")
            forward_frames = self._fetch_frames(symbols, request.start_date, request.end_date, adjust="forward")
        except Exception as exc:
            return AdjustmentResult(failed_symbols={symbol: str(exc) for symbol in symbols})
        if not isinstance(raw_frames, Mapping) or not isinstance(forward_frames, Mapping):
            reason = "unexpected TickFlow batch response"
            return AdjustmentResult(failed_symbols={symbol: reason for symbol in symbols})

        for symbol in symbols:
            try:
                raw = self._bars_by_date(raw_frames.get(symbol, pd.DataFrame()), symbol, Adjustment.RAW, request)
                forward = self._bars_by_date(
                    forward_frames.get(symbol, pd.DataFrame()), symbol, Adjustment.FORWARD, request
                )
                if not raw and not forward:
                    result.missing_symbols.append(symbol)
                    continue
                if raw.keys() != forward.keys():
                    missing_forward = sorted(raw.keys() - forward.keys())
                    missing_raw = sorted(forward.keys() - raw.keys())
                    raise ValueError(
                        "raw/forward date coverage mismatch: "
                        f"missing_forward={missing_forward} missing_raw={missing_raw}"
                    )

                factors = []
                for trade_date in sorted(raw):
                    raw_bar = raw[trade_date]
                    forward_bar = forward[trade_date]
                    ratios = []
                    for field in PRICE_FIELDS:
                        raw_value = float(getattr(raw_bar, field))
                        adjusted_value = float(getattr(forward_bar, field))
                        if not math.isfinite(raw_value) or raw_value <= 0:
                            raise ValueError(f"invalid raw {field} on {trade_date}: {raw_value}")
                        ratio = adjusted_value / raw_value
                        if not math.isfinite(ratio) or ratio <= 0:
                            raise ValueError(f"invalid {field} adjustment ratio on {trade_date}: {ratio}")
                        ratios.append(ratio)
                    close_ratio = ratios[-1]
                    if not all(
                        math.isclose(
                            ratio,
                            close_ratio,
                            rel_tol=TICKFLOW_FACTOR_REL_TOLERANCE,
                            abs_tol=TICKFLOW_FACTOR_REL_TOLERANCE,
                        )
                        for ratio in ratios[:-1]
                    ):
                        raise ValueError(
                            f"inconsistent OHLC adjustment ratios on {trade_date}: "
                            + ", ".join(f"{field}={ratio:.12g}" for field, ratio in zip(PRICE_FIELDS, ratios))
                        )
                    factors.append(AdjustmentFactor(symbol, trade_date, close_ratio, self.name))

                self._require_current_anchor(symbol, request, factors)
                result.factors[symbol] = factors
                result.providers_used[symbol] = self.name
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
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

    def _bars_by_date(self, frame, symbol, adjustment, request):
        multiplier = 100 if infer_market(symbol).value == "CN" else 1
        bars = bars_from_frame(
            frame,
            symbol=symbol,
            provider=self.name,
            interval="1d",
            adjustment=adjustment,
            volume_multiplier=multiplier,
        )
        return {bar.trade_date: bar for bar in bars if request.start_date <= bar.trade_date <= request.end_date}

    @staticmethod
    def _require_current_anchor(symbol, request, factors) -> None:
        if not factors:
            raise ValueError("TickFlow returned no in-window daily adjustment factors")
        market = infer_market(symbol)
        market_today = datetime.now(MARKET_TIMEZONES[market]).date()
        if request.end_date < market_today - timedelta(days=TICKFLOW_LATEST_FACTOR_LOOKBACK_DAYS):
            return
        latest = factors[-1]
        if latest.trade_date < request.end_date - timedelta(days=TICKFLOW_LATEST_FACTOR_LOOKBACK_DAYS):
            return
        if not math.isclose(latest.factor, 1.0, rel_tol=1e-6, abs_tol=1e-8):
            raise ValueError(
                f"latest forward adjustment factor is not anchored at 1.0: "
                f"date={latest.trade_date} factor={latest.factor}"
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

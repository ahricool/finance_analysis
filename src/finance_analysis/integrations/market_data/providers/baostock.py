"""BaoStock raw daily provider with one reused authenticated session."""

from __future__ import annotations

from threading import RLock
from typing import Any

import pandas as pd

from finance_analysis.integrations.market_data.models import (
    Adjustment,
    BatchBarResult,
    BatchInstrumentResult,
    DailyBarsRequest,
    InstrumentInfo,
    InstrumentRequest,
    Market,
)
from finance_analysis.integrations.market_data.normalizer import (
    bars_from_frame,
    canonical_symbol,
    currency_for_market,
)


def _result_to_dataframe(result: Any) -> pd.DataFrame:
    if str(getattr(result, "error_code", "0")) != "0":
        raise RuntimeError(f"BaoStock query failed: {getattr(result, 'error_msg', 'unknown')}")
    fields = list(getattr(result, "fields", []) or [])
    if not fields:
        raise RuntimeError("BaoStock result has no fields")
    rows = []
    while result.next():
        row = result.get_row_data()
        if len(row) != len(fields):
            raise RuntimeError("BaoStock row shape does not match fields")
        rows.append(row)
    return pd.DataFrame(rows, columns=fields)


class BaoStockProvider:
    name = "baostock"

    def __init__(self, *, sdk: Any = None) -> None:
        self._sdk = sdk
        self._logged_in = False
        self._lock = RLock()

    def _get_sdk(self):
        if self._sdk is None:
            import baostock

            self._sdk = baostock
        return self._sdk

    def _session(self):
        sdk = self._get_sdk()
        if not self._logged_in:
            response = sdk.login()
            if str(response.error_code) != "0":
                raise ConnectionError(f"BaoStock login failed: {response.error_msg}")
            self._logged_in = True
        return sdk

    def close(self) -> None:
        with self._lock:
            if self._logged_in:
                self._get_sdk().logout()
                self._logged_in = False

    @staticmethod
    def _provider_symbol(symbol: str) -> str:
        canonical = canonical_symbol(symbol, Market.CN)
        code, exchange = canonical.split(".")
        if exchange == "BJ":
            raise ValueError(f"BaoStock does not support Beijing Exchange symbol {symbol}")
        return f"{exchange.lower()}.{code}"

    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult:
        if request.adjustment is not Adjustment.RAW:
            raise ValueError("BaoStock storage reads must use adjustment='raw'")
        result = BatchBarResult()
        for value in request.symbols:
            symbol = canonical_symbol(value, Market.CN)
            try:
                with self._lock:
                    cursor = self._session().query_history_k_data_plus(
                        self._provider_symbol(symbol),
                        "date,open,high,low,close,volume,amount",
                        start_date=request.start_date.isoformat(),
                        end_date=request.end_date.isoformat(),
                        frequency="d",
                        adjustflag="3",
                    )
                    frame = _result_to_dataframe(cursor)
                bars = bars_from_frame(
                    frame,
                    symbol=symbol,
                    provider=self.name,
                    interval="1d",
                    adjustment=Adjustment.RAW,
                )
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult:
        result = BatchInstrumentResult()
        for value in request.symbols:
            symbol = canonical_symbol(value, Market.CN)
            try:
                with self._lock:
                    cursor = self._session().query_stock_basic(code=self._provider_symbol(symbol))
                    frame = _result_to_dataframe(cursor)
                if frame.empty:
                    result.missing_symbols.append(symbol)
                    continue
                row = frame.iloc[0]
                name = str(row.get("code_name") or "").strip()
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
                    instrument_type=str(row.get("type") or "stock"),
                )
                result.providers_used[symbol] = self.name
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result


__all__ = ["BaoStockProvider", "_result_to_dataframe"]

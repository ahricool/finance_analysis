"""Narrow CN 5-minute provider backed by AKShare's Sina minute API.

This is not a restored full-capability AkShareProvider. It only implements
interval=5m for CN symbols via ``ak.stock_zh_a_minute(..., period="5", adjust="")``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import (  # pragma: allowlist secret
    Adjustment,
    BatchBarResult,
    MarketBar,
    MinuteBarsRequest,
)
from finance_analysis.integrations.market_data.normalizer import canonical_symbol, infer_market  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import Market  # pragma: allowlist secret

SHANGHAI = ZoneInfo("Asia/Shanghai")
INTERVAL = timedelta(minutes=5)


def to_sina_symbol(code: str) -> str:
    canonical = canonical_symbol(code)
    if canonical.endswith(".SH"):
        return f"sh{canonical[:-3].lower()}"
    if canonical.endswith(".SZ"):
        return f"sz{canonical[:-3].lower()}"
    raise ValueError(f"SinaMinuteProvider only supports SH/SZ symbols, got {code}")


def _akshare_minute(sina_symbol: str) -> pd.DataFrame:
    import akshare as ak

    frame = ak.stock_zh_a_minute(symbol=sina_symbol, period="5", adjust="")
    return pd.DataFrame() if frame is None else frame


class SinaMinuteProvider:
    name = "sina_minute"

    def __init__(self, fetch_frame: Callable[[str], pd.DataFrame] | None = None) -> None:
        self._fetch_frame = fetch_frame or _akshare_minute

    def fetch_minute_bars(self, request: MinuteBarsRequest) -> BatchBarResult:
        if request.interval != "5m":
            raise ValueError("SinaMinuteProvider only implements interval=5m")
        result = BatchBarResult()
        fetched_at = utc_now()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            try:
                if infer_market(symbol) is not Market.CN:
                    raise ValueError(f"SinaMinuteProvider is CN-only, got {symbol}")
                sina_symbol = to_sina_symbol(symbol)
                frame = self._fetch_frame(sina_symbol)
                bars = self._bars_from_frame(frame, symbol=symbol, start=request.start_time, end=request.end_time)
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
                result.request_errors[symbol] = str(exc)
        result.fetched_at = fetched_at
        return result

    def _bars_from_frame(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[MarketBar]:
        if frame is None or frame.empty:
            return []
        renamed = frame.rename(columns={str(column): str(column).strip().lower() for column in frame.columns})
        time_col = next((name for name in ("day", "datetime", "time", "日期") if name in renamed.columns), None)
        if time_col is None:
            return []
        bars: list[MarketBar] = []
        for _, row in renamed.iterrows():
            parsed = pd.to_datetime(row[time_col], errors="coerce")
            if pd.isna(parsed):
                continue
            bar_end = parsed.to_pydatetime()
            if bar_end.tzinfo is None:
                bar_end = bar_end.replace(tzinfo=SHANGHAI)
            bar_end = bar_end.astimezone(timezone.utc)
            bar_start = bar_end - INTERVAL
            if bar_end <= start or bar_start >= end:
                continue
            open_price = _number(row.get("open"))
            high = _number(row.get("high"))
            low = _number(row.get("low"))
            close = _number(row.get("close"))
            volume = _number(row.get("volume"))
            if None in (open_price, high, low, close, volume):
                continue
            amount = _number(row.get("amount"))
            bars.append(
                MarketBar(
                    symbol=symbol,
                    market=Market.CN,
                    interval="5m",
                    trade_date=bar_end.astimezone(SHANGHAI).date(),
                    bar_time=bar_end,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=int(volume),
                    amount=amount,
                    currency="CNY",
                    adjustment=Adjustment.RAW,
                    provider=self.name,
                    amount_estimated=False,
                    bar_start=bar_start,
                    bar_end=bar_end,
                )
            )
        unique = {bar.bar_end: bar for bar in bars}
        return [unique[key] for key in sorted(unique)]


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number

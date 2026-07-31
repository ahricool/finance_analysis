"""Provider-independent symbol, unit, timezone, and currency normalization."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from .codes import is_bse_code, normalize_stock_code
from .models import Adjustment, Market, MarketBar, MarketQuote, market_from_value

MARKET_CURRENCIES = {
    Market.CN: "CNY",
    Market.US: "USD",
    Market.HK: "HKD",
    Market.SG: "SGD",
}
MARKET_TIMEZONES = {
    Market.CN: ZoneInfo("Asia/Shanghai"),
    Market.US: ZoneInfo("America/New_York"),
    Market.HK: ZoneInfo("Asia/Hong_Kong"),
    Market.SG: ZoneInfo("Asia/Singapore"),
}
STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


def infer_market(symbol: str) -> Market:
    value = str(symbol).strip().upper()
    if value.endswith(".US"):
        return Market.US
    if value.endswith(".HK") or value.startswith("HK") or (value.isdigit() and len(value) == 5):
        return Market.HK
    if value.endswith(".SG"):
        return Market.SG
    if value.endswith((".SH", ".SZ", ".BJ")) or value.startswith(("SH", "SZ", "BJ")):
        return Market.CN
    if value.isdigit() and len(value) == 6:
        return Market.CN
    return Market.US


def canonical_symbol(symbol: str, market: Market | str | None = None) -> str:
    value = str(symbol or "").strip().upper()
    if not value:
        raise ValueError("symbol must not be empty")
    resolved = market_from_value(market) if market is not None else infer_market(value)
    if resolved is Market.US:
        return value if value.endswith(".US") else f"{value}.US"
    if resolved is Market.SG:
        return value if value.endswith(".SG") else f"{value}.SG"
    if resolved is Market.HK:
        base = value.removeprefix("HK")
        if base.endswith(".HK"):
            base = base[:-3]
        if not base.isdigit():
            raise ValueError(f"Invalid HK symbol: {symbol!r}")
        return f"{int(base)}.HK"
    base = normalize_stock_code(value)
    if not base.isdigit() or len(base) != 6:
        raise ValueError(f"Invalid CN symbol: {symbol!r}")
    if value.endswith(".BJ") or value.startswith("BJ") or is_bse_code(base):
        return f"{base}.BJ"
    exchange = "SH" if base.startswith(("5", "6", "9")) else "SZ"
    return f"{base}.{exchange}"


def normalize_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(canonical_symbol(symbol) for symbol in symbols))


def currency_for_market(market: Market | str) -> str:
    return MARKET_CURRENCIES[market_from_value(market)]


def _number(value: Any) -> float | None:
    if value is None or value is pd.NA:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def bars_from_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    provider: str,
    interval: str,
    adjustment: Adjustment | str = Adjustment.RAW,
    volume_multiplier: int = 1,
    amount_estimated: bool = False,
) -> list[MarketBar]:
    canonical = canonical_symbol(symbol)
    market = infer_market(canonical)
    if frame is None or frame.empty:
        return []
    bars: list[MarketBar] = []
    for _, series in frame.iterrows():
        row = series.to_dict()
        raw_date = _value(row, "trade_date", "date", "日期", "Date")
        raw_time = _value(row, "bar_time", "trade_time", "timestamp", "datetime", "Datetime")
        bar_time: datetime | None = None
        if interval == "1d":
            parsed_date = pd.to_datetime(raw_date if raw_date is not None else raw_time, errors="coerce")
            if pd.isna(parsed_date):
                continue
            trade_date = parsed_date.date()
        else:
            parsed_time = pd.to_datetime(raw_time if raw_time is not None else raw_date, errors="coerce")
            if pd.isna(parsed_time):
                continue
            bar_time = parsed_time.to_pydatetime()
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=MARKET_TIMEZONES[market])
            bar_time = bar_time.astimezone(timezone.utc)
            trade_date = bar_time.astimezone(MARKET_TIMEZONES[market]).date()
        open_price = _number(_value(row, "open", "Open", "开盘"))
        high = _number(_value(row, "high", "High", "最高"))
        low = _number(_value(row, "low", "Low", "最低"))
        close = _number(_value(row, "close", "Close", "收盘"))
        volume = _number(_value(row, "volume", "Volume", "成交量"))
        if None in (open_price, high, low, close, volume):
            continue
        amount = _number(_value(row, "amount", "turnover", "Turnover", "成交额"))
        bars.append(
            MarketBar(
                symbol=canonical,
                market=market,
                interval=interval,
                trade_date=trade_date,
                bar_time=bar_time,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=int(volume * volume_multiplier),
                amount=amount,
                currency=currency_for_market(market),
                adjustment=adjustment,
                provider=provider,
                amount_estimated=amount_estimated,
            )
        )
    identity = (lambda bar: bar.trade_date) if interval == "1d" else (lambda bar: bar.bar_time)
    return sorted({identity(bar): bar for bar in bars}.values(), key=identity)


def quote_from_value(value: Any, *, symbol: str, provider: str) -> MarketQuote | None:
    if value is None:
        return None
    canonical = canonical_symbol(symbol)
    market = infer_market(canonical)
    source = value if isinstance(value, Mapping) else vars(value)
    price = _number(_value(source, "price", "last_done", "last_price", "current"))
    if price is None or price <= 0:
        return None
    volume = _number(_value(source, "volume"))
    quote_time_value = _value(source, "quote_time", "snapshot_time", "timestamp", "time")
    quote_time = None
    if quote_time_value is not None:
        parsed = pd.to_datetime(quote_time_value, errors="coerce", utc=True)
        if not pd.isna(parsed):
            quote_time = parsed.to_pydatetime()
    return MarketQuote(
        symbol=canonical,
        market=market,
        provider=provider,
        currency=currency_for_market(market),
        name=str(_value(source, "name") or ""),
        price=price,
        change_pct=_number(_value(source, "change_pct", "change_rate")),
        change_amount=_number(_value(source, "change_amount", "change")),
        volume=int(volume) if volume is not None else None,
        amount=_number(_value(source, "amount", "turnover")),
        volume_ratio=_number(_value(source, "volume_ratio")),
        turnover_rate=_number(_value(source, "turnover_rate")),
        amplitude=_number(_value(source, "amplitude")),
        open_price=_number(_value(source, "open_price", "open")),
        high=_number(_value(source, "high")),
        low=_number(_value(source, "low")),
        pre_close=_number(_value(source, "pre_close", "prev_close", "prev_close_price")),
        pe_ratio=_number(_value(source, "pe_ratio")),
        pb_ratio=_number(_value(source, "pb_ratio")),
        total_mv=_number(_value(source, "total_mv")),
        circ_mv=_number(_value(source, "circ_mv")),
        quote_time=quote_time,
    )


def local_midnight_timestamp_ms(value: date, market: Market | str) -> int:
    local = datetime.combine(value, time.min, tzinfo=MARKET_TIMEZONES[market_from_value(market)])
    return int(local.timestamp() * 1000)

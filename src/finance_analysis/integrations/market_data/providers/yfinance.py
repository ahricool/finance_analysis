"""Yahoo Finance provider for forward-adjusted daily bars, quotes, indices, and metadata."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

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

_US_INDICES = (
    ("SPX.US", "^GSPC", "标普500指数"),
    ("DJI.US", "^DJI", "道琼斯工业指数"),
    ("IXIC.US", "^IXIC", "纳斯达克综合指数"),
    ("NDX.US", "^NDX", "纳斯达克100指数"),
    ("VIX.US", "^VIX", "VIX恐慌指数"),
    ("RUT.US", "^RUT", "罗素2000指数"),
)
_HK_INDICES = (
    ("HSI.HK", "^HSI", "恒生指数"),
    ("HSCEI.HK", "^HSCE", "恒生中国企业指数"),
    ("HSTECH.HK", "^HSTECH", "恒生科技指数"),
)


class YFinanceProvider:
    name = "yfinance"

    def __init__(self, *, batch_size: int = 100, max_workers: int = 3, max_retries: int = 2) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_retries < 0:
            raise ValueError("max_retries must be at least 0")
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.max_retries = max_retries

    @staticmethod
    def to_yfinance_symbol(code: str) -> str:
        canonical = canonical_symbol(code)
        if canonical.endswith(".US"):
            return canonical[:-3].replace(".", "-")
        if canonical.endswith(".HK"):
            return f"{int(canonical[:-3]):04d}.HK"
        if canonical.endswith(".SH"):
            return f"{canonical[:-3]}.SS"
        if canonical.endswith(".SZ"):
            return canonical
        raise ValueError(f"Yahoo Finance does not support {code}")

    @staticmethod
    def _ticker_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        if not isinstance(raw.columns, pd.MultiIndex):
            return raw.copy()
        for level in range(raw.columns.nlevels):
            if ticker in set(raw.columns.get_level_values(level)):
                return raw.xs(ticker, axis=1, level=level, drop_level=True).copy()
        return pd.DataFrame()

    def _download(self, symbols: list[str], *, auto_adjust: bool = False, **kwargs: Any) -> pd.DataFrame:
        import yfinance as yf

        return yf.download(
            tickers=symbols,
            progress=False,
            auto_adjust=auto_adjust,
            prepost=False,
            group_by="ticker",
            multi_level_index=True,
            threads=self.max_workers,
            **kwargs,
        )

    def _batches(self, values: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
        return [values[index : index + self.batch_size] for index in range(0, len(values), self.batch_size)]

    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult:
        if request.adjustment is not Adjustment.FORWARD:
            raise ValueError("Yahoo daily storage reads require adjustment='forward'")
        symbols = [canonical_symbol(value) for value in request.symbols]
        provider_symbols = [self.to_yfinance_symbol(symbol) for symbol in symbols]
        result = BatchBarResult()
        for batch in self._batches(list(zip(symbols, provider_symbols))):
            pending = list(batch)
            errors: dict[str, str] = {}
            for _attempt in range(self.max_retries + 1):
                if not pending:
                    break
                try:
                    raw = self._download(
                        [provider_symbol for _, provider_symbol in pending],
                        start=request.start_date,
                        end=request.end_date + timedelta(days=1),
                        interval="1d",
                        actions=False,
                        auto_adjust=True,
                    )
                except Exception as exc:
                    errors.update({symbol: str(exc) for symbol, _ in pending})
                    continue
                next_pending: list[tuple[str, str]] = []
                for symbol, provider_symbol in pending:
                    frame = self._ticker_frame(raw, provider_symbol).reset_index()
                    bars = bars_from_frame(
                        frame,
                        symbol=symbol,
                        provider=self.name,
                        interval="1d",
                        adjustment=Adjustment.FORWARD,
                    )
                    if bars:
                        result.data[symbol] = bars
                        result.providers_used[symbol] = self.name
                        errors.pop(symbol, None)
                    else:
                        next_pending.append((symbol, provider_symbol))
                pending = next_pending
            for symbol, _ in pending:
                if symbol in errors:
                    result.failed_symbols[symbol] = errors[symbol]
                else:
                    result.missing_symbols.append(symbol)
        return result

    def fetch_minute_bars(self, request: MinuteBarsRequest) -> BatchBarResult:
        symbols = [canonical_symbol(value) for value in request.symbols]
        provider_symbols = [self.to_yfinance_symbol(symbol) for symbol in symbols]
        result = BatchBarResult()
        try:
            raw = self._download(
                provider_symbols,
                start=request.start_time,
                end=request.end_time,
                interval=request.interval,
                actions=False,
            )
        except Exception as exc:
            return BatchBarResult(failed_symbols={symbol: str(exc) for symbol in symbols})
        for symbol, provider_symbol in zip(symbols, provider_symbols):
            frame = self._ticker_frame(raw, provider_symbol).reset_index()
            bars = bars_from_frame(frame, symbol=symbol, provider=self.name, interval=request.interval)
            if bars:
                result.data[symbol] = bars
                result.providers_used[symbol] = self.name
            else:
                result.missing_symbols.append(symbol)
        return result

    def fetch_quotes(self, request: QuoteRequest) -> BatchQuoteResult:
        import yfinance as yf

        result = BatchQuoteResult()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            try:
                ticker = yf.Ticker(self.to_yfinance_symbol(symbol))
                fast = dict(ticker.fast_info)
                previous = fast.get("previous_close")
                price = fast.get("last_price")
                payload = {
                    "name": "",
                    "price": price,
                    "pre_close": previous,
                    "change_amount": price - previous if price is not None and previous is not None else None,
                    "change_pct": ((price / previous - 1) * 100 if price is not None and previous else None),
                    "open": fast.get("open"),
                    "high": fast.get("day_high"),
                    "low": fast.get("day_low"),
                    "volume": fast.get("last_volume"),
                    "amount": None,
                }
                quote = quote_from_value(payload, symbol=symbol, provider=self.name)
                if quote is None:
                    result.missing_symbols.append(symbol)
                else:
                    result.data[symbol] = quote
                    result.providers_used[symbol] = self.name
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult:
        import yfinance as yf

        result = BatchInstrumentResult()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            market = infer_market(symbol)
            try:
                info = yf.Ticker(self.to_yfinance_symbol(symbol)).get_info()
                name = str(info.get("longName") or info.get("shortName") or "").strip()
                if not name:
                    result.missing_symbols.append(symbol)
                    continue
                result.data[symbol] = InstrumentInfo(
                    symbol=symbol,
                    market=market,
                    name=name,
                    provider=self.name,
                    currency=str(info.get("currency") or currency_for_market(market)),
                    exchange=str(info.get("exchange") or "") or None,
                    instrument_type=str(info.get("quoteType") or "") or None,
                )
                result.providers_used[symbol] = self.name
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def get_indices(self, market: Market) -> list[MarketIndex]:
        import yfinance as yf

        mappings = _US_INDICES if market is Market.US else _HK_INDICES if market is Market.HK else ()
        result: list[MarketIndex] = []
        for symbol, provider_symbol, name in mappings:
            try:
                fast = dict(yf.Ticker(provider_symbol).fast_info)
                price = float(fast.get("last_price") or 0)
                previous = float(fast.get("previous_close") or 0)
                if price <= 0:
                    continue
                result.append(
                    MarketIndex(
                        symbol=symbol,
                        name=name,
                        market=market,
                        provider=self.name,
                        price=price,
                        change=price - previous if previous else 0,
                        change_pct=(price / previous - 1) * 100 if previous else 0,
                        volume=int(fast["last_volume"]) if fast.get("last_volume") is not None else None,
                        amount=None,
                    )
                )
            except Exception:
                continue
        return result


__all__ = ["YFinanceProvider"]

"""Yahoo Finance provider for forward-adjusted daily bars, quotes, indices, and metadata."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import partial
import ast
import re
import logging
import threading
from typing import Any

import pandas as pd

from finance_analysis.core.retry import retry_call, transient_error, wait_before_retry
from finance_analysis.integrations.market_data.bounded_requests import bounded_results, budgeted_retry
from finance_analysis.integrations.market_data.batch_pacing import before_daily_batch, daily_batch_scope  # pragma: allowlist secret

from finance_analysis.integrations.market_data.models import (  # pragma: allowlist secret
    Adjustment,
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentInfo,
    InstrumentRequest,
    Market,
    MarketBar,
    MarketIndex,
    MarketQuote,
    MinuteBarsRequest,
    QuoteRequest,
)
from finance_analysis.integrations.market_data.normalizer import (  # pragma: allowlist secret
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


YFINANCE_SYMBOL_OVERRIDES = {symbol: ticker for symbol, ticker, _ in (*_US_INDICES, *_HK_INDICES)}


QUOTE_WORKERS = 6
_QUOTE_EXECUTOR = ThreadPoolExecutor(max_workers=QUOTE_WORKERS, thread_name_prefix="yfinance-quote")


class YFinanceProvider:
    name = "yfinance"

    # Listed US exchanges; OTC securities are outside the market heatmap.
    SNAPSHOT_EXCHANGES = ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS")

    @staticmethod
    def from_yfinance_symbol(symbol):
        # Yahoo uses BRK-B / BF-B, while the canonical master uses BRK.B / BF.B.
        return canonical_symbol(re.sub(r"-([A-Z])$", r".\1", symbol.upper()), "US")

    @staticmethod
    def _screen_rows(query, *, best_effort=False):
        """Strict reference-data pagination by default; live snapshots may opt into partial results."""
        if best_effort:
            return YFinanceProvider._best_effort_screen_rows(query)
        import yfinance as yf

        rows, seen, total = [], set(), None
        for offset in range(0, 50000, 250):
            payload = retry_call(lambda: yf.screen(query, size=250, offset=offset,
                                                  sortField="ticker", sortAsc=True))
            current_total = int(payload["total"])
            page = payload["quotes"]
            if total is not None and current_total != total:
                raise ValueError("Yahoo screener size changed during pagination")
            total = current_total
            if payload.get("start") != offset or not isinstance(page, list):
                raise ValueError("Yahoo screener returned an unexpected page")
            for row in page:
                symbol = row.get("symbol")
                if not symbol or symbol in seen:
                    raise ValueError("Yahoo screener returned duplicate or missing symbols")
                seen.add(symbol)
                rows.append(row)
            if len(rows) == total:
                return rows
            if not page or len(rows) > total:
                raise ValueError("Yahoo screener returned incomplete pagination")
        raise ValueError("Yahoo screener exceeded page bound")

    @staticmethod
    def _best_effort_screen_rows(query):
        """A live screen is not an atomic snapshot; retain usable pages and deduplicate."""
        import yfinance as yf

        logger = logging.getLogger(__name__)
        rows, total, stalled, failures = {}, None, 0, 0
        for offset in range(0, 50000, 250):
            try:
                payload = retry_call(lambda: yf.screen(query, size=250, offset=offset,
                                                      sortField="ticker", sortAsc=True))
                if not isinstance(payload, dict) or not isinstance(payload.get("quotes"), list):
                    raise ValueError("Yahoo screener returned an invalid page")
            except Exception as exc:
                if not rows:
                    raise
                failures += 1
                logger.warning("Yahoo snapshot page unavailable offset=%s collected=%s error_type=%s",
                               offset, len(rows), type(exc).__name__)
                # Skip an isolated bad page when later pages are known to exist.
                if failures < 2 and total is not None and offset + 250 < total:
                    continue
                return list(rows.values())
            failures = 0
            try:
                current_total = int(payload["total"])
            except (KeyError, TypeError, ValueError, OverflowError):
                current_total = None
            if current_total != total or payload.get("start") != offset:
                logger.info("Yahoo snapshot pagination offset=%s start=%s previous_total=%s total=%s collected=%s",
                            offset, payload.get("start"), total, current_total, len(rows))
            total = current_total
            page = payload["quotes"]
            before, duplicates, invalid = len(rows), 0, 0
            for row in page:
                symbol = row.get("symbol") if isinstance(row, dict) else None
                if not isinstance(symbol, str) or not symbol.strip():
                    invalid += 1
                    continue
                if symbol in rows:
                    duplicates += 1
                    continue
                rows[symbol] = row
            if duplicates or invalid:
                logger.info("Yahoo snapshot page offset=%s duplicates=%s invalid=%s collected=%s",
                            offset, duplicates, invalid, len(rows))
            stalled = stalled + 1 if len(rows) == before else 0
            if not page or (len(page) < 250 and (total is None or offset + len(page) >= total)):
                return list(rows.values())
            if stalled >= 2:
                logger.warning("Yahoo snapshot pagination stopped without progress offset=%s collected=%s",
                               offset, len(rows))
                return list(rows.values())
        logger.warning("Yahoo snapshot pagination reached page bound collected=%s", len(rows))
        return list(rows.values())

    def fetch_market_snapshot(self, market: Market, *, include_names=True, min_market_cap=0) -> BatchQuoteResult:
        import yfinance as yf

        if market != Market.US:
            raise ValueError("Yahoo full-market snapshots support US only")
        query = yf.EquityQuery("AND", [
            yf.EquityQuery("EQ", ["region", "us"]),
            yf.EquityQuery("IS-IN", ["exchange", *self.SNAPSHOT_EXCHANGES]),
            yf.EquityQuery("GTE", ["intradaymarketcap", max(1, min_market_cap)]),
        ])
        result = BatchQuoteResult()
        for row in self._screen_rows(query, best_effort=True):
            # Yahoo can return funds despite an EquityQuery. Check each result.
            if row.get("quoteType") != "EQUITY" or row.get("exchange") not in self.SNAPSHOT_EXCHANGES:
                continue
            symbol = row["symbol"]
            try:
                symbol = self.from_yfinance_symbol(symbol)
                stamp = row.get("regularMarketTime")
                quote = MarketQuote(
                    symbol=symbol, market=market, provider=self.name, currency=str(row.get("currency") or "USD"),
                    name=str(row.get("longName") or row.get("shortName") or "") if include_names else "",
                    price=row.get("regularMarketPrice"), change_pct=row.get("regularMarketChangePercent"),
                    pre_close=row.get("regularMarketPreviousClose"), volume=row.get("regularMarketVolume"),
                    open_price=row.get("regularMarketOpen"), high=row.get("regularMarketDayHigh"),
                    low=row.get("regularMarketDayLow"), total_mv=row.get("marketCap"),
                    quote_time=datetime.fromtimestamp(stamp, timezone.utc) if stamp else None,
                )
                from ..validator import validate_quote

                result.data[symbol] = validate_quote(quote)
                result.providers_used[symbol] = self.name
            except (TypeError, ValueError, OverflowError) as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def fetch_stock_classifications(self, market: Market) -> dict[str, dict]:
        """Bulk industry membership from explicit Yahoo industry screens, weekly only."""
        import yfinance as yf

        if market != Market.US:
            raise ValueError("Yahoo stock classifications support US only")
        industries = yf.EquityQuery("EQ", ["region", "us"]).valid_values["industry"]
        result = {}
        for sector, names in industries.items():
            for industry in sorted(names):
                query = yf.EquityQuery("AND", [
                    yf.EquityQuery("EQ", ["region", "us"]),
                    yf.EquityQuery("EQ", ["industry", industry]),
                ])
                for row in self._screen_rows(query):
                    if row.get("quoteType") != "EQUITY":
                        continue
                    code = self.from_yfinance_symbol(row["symbol"])
                    classification = {"sector": sector, "industry": industry, "source": "yfinance"}
                    if code in result and result[code] != classification:
                        raise ValueError("Conflicting Yahoo industry classifications")
                    result[code] = classification
        if not result:
            raise ValueError("Yahoo returned no industry classifications")
        return result

    def __init__(self, *, batch_size: int = 100, max_workers: int = 3, max_retries: int = 3) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_retries < 0:
            raise ValueError("max_retries must be at least 0")
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.max_retries = min(max_retries, 3)

    @staticmethod
    def to_yfinance_symbol(code: str) -> str:
        # HK index identities are nonnumeric and cannot use the stock normalizer.
        value = str(code).strip().upper()
        canonical = value if value in YFINANCE_SYMBOL_OVERRIDES else canonical_symbol(code)
        if canonical in YFINANCE_SYMBOL_OVERRIDES:
            return YFINANCE_SYMBOL_OVERRIDES[canonical]
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

        # yf.download logs per-ticker exceptions instead of raising them. Capture
        # its per-call summary without losing the existing threaded batch path.
        errors = {}
        caller = threading.get_ident()

        class DownloadErrors(logging.Handler):
            def emit(self, record):
                message = record.getMessage()
                if record.thread != caller or record.levelno < logging.ERROR or "]: " not in message:
                    return
                tickers, reason = message.split("]: ", 1)
                try:
                    failed = ast.literal_eval(tickers + "]")
                except (ValueError, SyntaxError):
                    return
                for ticker in failed:
                    if ticker in symbols:
                        errors[ticker] = reason

        logger = logging.getLogger("yfinance")
        handler = DownloadErrors()
        logger.addHandler(handler)
        try:
            frame = yf.download(
                tickers=symbols,
                progress=False,
                auto_adjust=auto_adjust,
                prepost=False,
                group_by="ticker",
                multi_level_index=True,
                threads=self.max_workers,
                **kwargs,
            )
        finally:
            logger.removeHandler(handler)
        if frame is None:
            frame = pd.DataFrame()
        frame.attrs["request_errors"] = errors
        return frame

    def _download_retried(self, symbols: list[str], **kwargs: Any) -> pd.DataFrame:
        """Retain successful tickers and retry only missing/failed Yahoo batch members."""
        pending = list(symbols)
        frames = {}
        errors = {}
        for attempt in range(self.max_retries + 1):
            if not pending:
                break
            if attempt:
                wait_before_retry(attempt - 1)
            try:
                raw = self._download(pending, **kwargs)
            except Exception as exc:
                if not transient_error(exc):
                    raise
                errors.update({symbol: type(exc).__name__ for symbol in pending})
                continue
            reported = raw.attrs.get("request_errors", {})
            for symbol in list(pending):
                frame = self._ticker_frame(raw, symbol).dropna(how="all")
                if symbol in reported:
                    errors[symbol] = reported[symbol]
                elif not frame.empty:
                    frames[symbol] = frame
                    pending.remove(symbol)
                    errors.pop(symbol, None)
        result = pd.concat(frames, axis=1) if frames else pd.DataFrame()
        result.attrs["request_errors"] = errors
        return result

    def _batches(self, values: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
        return [values[index : index + self.batch_size] for index in range(0, len(values), self.batch_size)]

    @daily_batch_scope()
    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult:
        if request.adjustment is not Adjustment.FORWARD:
            raise ValueError("Yahoo daily storage reads require adjustment='forward'")
        symbols = [canonical_symbol(value) for value in request.symbols]
        provider_symbols = [self.to_yfinance_symbol(symbol) for symbol in symbols]
        result = BatchBarResult()
        for batch in self._batches(list(zip(symbols, provider_symbols))):
            before_daily_batch()
            pending = list(batch)
            errors: dict[str, str] = {}
            for _attempt in range(self.max_retries + 1):
                if not pending:
                    break
                if _attempt:
                    wait_before_retry(_attempt - 1)
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
                    reason = f"request_failed: {str(exc) or type(exc).__name__}"
                    errors.update({symbol: reason for symbol, _ in pending})
                    result.request_errors.update({symbol: reason for symbol, _ in pending})
                    continue
                next_pending: list[tuple[str, str]] = []
                for symbol, provider_symbol in pending:
                    error = raw.attrs.get("request_errors", {}).get(provider_symbol)
                    if error:
                        result.request_errors[symbol] = error
                        errors[symbol] = error
                    try:
                        frame = self._ticker_frame(raw, provider_symbol).reset_index()
                        bars = bars_from_frame(
                            frame,
                            symbol=symbol,
                            provider=self.name,
                            interval="1d",
                            adjustment=Adjustment.FORWARD,
                            instrument_type="INDEX" if symbol in YFINANCE_SYMBOL_OVERRIDES else None,
                        )
                    except Exception as exc:
                        reason = f"parse_failed: {str(exc) or type(exc).__name__}"
                        errors[symbol] = reason
                        result.request_errors[symbol] = reason
                        next_pending.append((symbol, provider_symbol))
                        continue
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
        download_kwargs: dict[str, Any] = {
            "interval": request.interval,
            "actions": False,
            "auto_adjust": False,
            "back_adjust": False,
            "timeout": 8,
        }
        if request.period:
            download_kwargs["period"] = request.period
        else:
            download_kwargs["start"] = request.start_time
            download_kwargs["end"] = request.end_time
        try:
            raw = self._download_retried(provider_symbols, **download_kwargs)
        except Exception as exc:
            return BatchBarResult(failed_symbols={symbol: str(exc) for symbol in symbols})
        for symbol, provider_symbol in zip(symbols, provider_symbols):
            error = raw.attrs.get("request_errors", {}).get(provider_symbol)
            if error:
                result.failed_symbols[symbol] = error
                result.request_errors[symbol] = error
                continue
            frame = self._ticker_frame(raw, provider_symbol).reset_index()
            bars = bars_from_frame(frame, symbol=symbol, provider=self.name, interval=request.interval)
            if bars:
                result.data[symbol] = bars
                result.providers_used[symbol] = self.name
            else:
                result.missing_symbols.append(symbol)
        return result

    def fetch_intraday_preview_daily_bars(self, symbols: list[str], trade_date: date) -> BatchBarResult:
        """Batch 5-minute bars for one session and aggregate them into temporary daily bars."""
        canonical = [canonical_symbol(value) for value in symbols]
        provider_symbols = [self.to_yfinance_symbol(symbol) for symbol in canonical]
        result = BatchBarResult()
        for batch in self._batches(list(zip(canonical, provider_symbols))):
            pending = list(batch)
            try:
                raw = self._download_retried(
                    [provider_symbol for _, provider_symbol in pending],
                    interval="5m",
                    period="1d",
                    actions=False,
                    auto_adjust=False,
                )
            except Exception as exc:
                reason = str(exc) or type(exc).__name__
                logger = logging.getLogger(__name__)
                logger.exception("provider=%s action=intraday_preview_daily_bars failed", self.name)
                result.failed_symbols.update({symbol: reason for symbol, _ in pending})
                continue
            for symbol, provider_symbol in pending:
                error = raw.attrs.get("request_errors", {}).get(provider_symbol)
                if error:
                    result.failed_symbols[symbol] = error
                    continue
                frame = self._ticker_frame(raw, provider_symbol).reset_index()
                bars = bars_from_frame(frame, symbol=symbol, provider=self.name, interval="5m")
                session = [bar for bar in bars if bar.trade_date == trade_date]
                if not session:
                    result.missing_symbols.append(symbol)
                    continue
                session = sorted(
                    session,
                    key=lambda bar: bar.bar_time or datetime.min.replace(tzinfo=timezone.utc),
                )
                result.data[symbol] = [
                    MarketBar(
                        symbol=symbol,
                        market=infer_market(symbol),
                        interval="1d",
                        trade_date=trade_date,
                        bar_time=session[-1].bar_time,
                        open=session[0].open,
                        high=max(bar.high for bar in session),
                        low=min(bar.low for bar in session),
                        close=session[-1].close,
                        volume=int(sum(bar.volume for bar in session)),
                        amount=None,
                        currency=currency_for_market(infer_market(symbol)),
                        adjustment=Adjustment.RAW,
                        provider=self.name,
                    )
                ]
                result.providers_used[symbol] = self.name
        return result

    def fetch_quotes(self, request: QuoteRequest) -> BatchQuoteResult:
        result = BatchQuoteResult()
        calls = {
            canonical_symbol(value): partial(self._fetch_quote, canonical_symbol(value)) for value in request.symbols
        }
        for symbol, quote, error in bounded_results(calls, _QUOTE_EXECUTOR, min(self.max_workers, QUOTE_WORKERS)):
            if error is not None:
                result.failed_symbols[symbol] = str(error)
            elif quote is None:
                result.missing_symbols.append(symbol)
            else:
                result.data[symbol] = quote
                result.providers_used[symbol] = self.name
        return result

    def _fetch_quote(self, symbol):
        import yfinance as yf

        ticker = yf.Ticker(self.to_yfinance_symbol(symbol))
        if infer_market(symbol) is Market.US:
            # Keep OHLCV and its actual regular-session timestamp from one payload.
            info = budgeted_retry(lambda: ticker.info)
            stamp = info.get("regularMarketTime")
            quote_time = datetime.fromtimestamp(stamp, timezone.utc) if stamp else None
            fast = {
                "previous_close": info.get("regularMarketPreviousClose"),
                "last_price": info.get("regularMarketPrice"),
                "open": info.get("regularMarketOpen"),
                "day_high": info.get("regularMarketDayHigh"),
                "day_low": info.get("regularMarketDayLow"),
                "last_volume": info.get("regularMarketVolume"),
            }
        else:
            fast = budgeted_retry(lambda: dict(ticker.fast_info))
            quote_time = datetime.now(timezone.utc)
        previous = fast.get("previous_close")
        price = fast.get("last_price")
        payload = {
            "name": "",
            "quote_time": quote_time,
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
        return quote

    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult:
        import yfinance as yf

        result = BatchInstrumentResult()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            market = infer_market(symbol)
            try:
                info = retry_call(lambda: yf.Ticker(self.to_yfinance_symbol(symbol)).get_info())
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
        for symbol, _provider_symbol, name in mappings:
            try:
                fast = retry_call(lambda: dict(yf.Ticker(self.to_yfinance_symbol(symbol)).fast_info))
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

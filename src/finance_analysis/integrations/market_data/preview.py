"""Intraday preview bars for Trend Following and ETF Rotation. Isolated from ordinary provider fallback."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable

from .models import Adjustment, Market, MarketBar, MarketQuote, market_from_value
from .normalizer import canonical_symbol, currency_for_market

logger = logging.getLogger(__name__)

CN_PREVIEW_PROVIDER = "easyquotation_tencent"
US_PREVIEW_PROVIDER = "yfinance"
CN_SNAPSHOT_PROVIDER = "easyquotation"


class PreviewQuoteError(RuntimeError):
    """Raised when preview realtime quotes cannot be used."""


def daily_bar_from_quote(quote: MarketQuote, trade_date: date) -> MarketBar | None:
    prices = (quote.open_price, quote.high, quote.low, quote.price)
    if any(value is None or value <= 0 for value in prices):
        return None
    open_price, high, low, close = (float(quote.open_price), float(quote.high), float(quote.low), float(quote.price))
    if high < max(open_price, close, low) or low > min(open_price, close, high):
        return None
    return _market_bar(quote, trade_date, open_price=open_price, high=high, low=low, close=close)


def close_bar_from_quote(quote: MarketQuote, trade_date: date) -> MarketBar | None:
    """Build a temporary daily bar from last price, cumulative volume and amount.

    ETF Rotation only consumes close/volume/amount. Missing OHLC is filled from close.
    """
    if quote.price is None or quote.price <= 0:
        return None
    close = float(quote.price)
    open_price = float(quote.open_price) if quote.open_price is not None and quote.open_price > 0 else close
    high = float(quote.high) if quote.high is not None and quote.high > 0 else max(open_price, close)
    low = float(quote.low) if quote.low is not None and quote.low > 0 else min(open_price, close)
    return _market_bar(quote, trade_date, open_price=open_price, high=high, low=low, close=close)


def _market_bar(
    quote: MarketQuote,
    trade_date: date,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> MarketBar | None:
    volume = 0 if quote.volume is None else int(quote.volume)
    if volume < 0:
        return None
    amount = None if quote.amount is None else float(quote.amount)
    if amount is not None and amount < 0:
        return None
    return MarketBar(
        symbol=quote.symbol,
        market=quote.market,
        interval="1d",
        trade_date=trade_date,
        bar_time=None,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=amount,
        currency=quote.currency or currency_for_market(quote.market),
        adjustment=Adjustment.RAW,
        provider=quote.provider,
    )


def _easyquotation_provider(market_data: Any) -> Any | None:
    registry = getattr(market_data, "registry", None)
    if registry is None:
        return None
    try:
        provider = registry.get(CN_SNAPSHOT_PROVIDER).provider
    except Exception:
        logger.exception("market=CN provider=%s registry_lookup_failed", CN_PREVIEW_PROVIDER)
        return None
    if provider is None or not callable(getattr(provider, "fetch_quotes_for_codes", None)):
        return None
    return provider


def _bars_from_quotes(
    quotes: Any,
    wanted: set[str],
    trade_date: date,
    bars: dict[str, MarketBar],
    *,
    converter,
) -> None:
    for symbol, quote in getattr(quotes, "data", {}).items():
        if symbol not in wanted or symbol in bars:
            continue
        bar = converter(quote, trade_date)
        if bar is not None:
            bars[symbol] = bar


def _collect_us_preview_daily_bars(
    market_data: Any,
    wanted: tuple[str, ...],
    trade_date: date,
) -> tuple[dict[str, MarketBar], str, int]:
    provider = market_data.registry.get(US_PREVIEW_PROVIDER).provider
    result = provider.fetch_intraday_preview_daily_bars(list(wanted), trade_date)
    bars = {code: items[0] for code, items in result.data.items() if items}
    if result.failed_symbols:
        logger.warning(
            "market=US provider=%s preview_failed_symbols=%s",
            US_PREVIEW_PROVIDER,
            len(result.failed_symbols),
        )
    return bars, US_PREVIEW_PROVIDER, len(bars)


def collect_preview_daily_bars(
    market_data: Any,
    market: Market | str,
    symbols: Iterable[str],
    trade_date: date,
) -> tuple[dict[str, MarketBar], str, int]:
    resolved = market_from_value(market)
    wanted = tuple(dict.fromkeys(canonical_symbol(symbol) for symbol in symbols))
    if resolved is Market.CN:
        try:
            snapshot = market_data.get_market_snapshot(Market.CN, providers=(CN_SNAPSHOT_PROVIDER,))
        except Exception as exc:
            logger.exception("market=CN provider=%s snapshot_failed", CN_PREVIEW_PROVIDER)
            raise PreviewQuoteError(f"easyquotation tencent snapshot failed: {exc}") from exc
        if not snapshot.data:
            detail = snapshot.failed_symbols.get("CN") or snapshot.failed_symbols or "empty snapshot"
            raise PreviewQuoteError(f"easyquotation tencent snapshot failed: {detail}")
        wanted_set = set(wanted)
        bars: dict[str, MarketBar] = {}
        _bars_from_quotes(snapshot, wanted_set, trade_date, bars, converter=daily_bar_from_quote)
        missing = [symbol for symbol in wanted if symbol not in bars]
        if missing:
            provider = _easyquotation_provider(market_data)
            if provider is None:
                logger.warning(
                    "market=CN provider=%s real_fill_skipped missing=%s",
                    CN_PREVIEW_PROVIDER,
                    len(missing),
                )
            else:
                try:
                    extra = provider.fetch_quotes_for_codes(missing)
                except Exception:
                    logger.exception(
                        "market=CN provider=%s real_fill_failed missing=%s",
                        CN_PREVIEW_PROVIDER,
                        len(missing),
                    )
                else:
                    _bars_from_quotes(extra, wanted_set, trade_date, bars, converter=daily_bar_from_quote)
                    logger.info(
                        "market=CN provider=%s snapshot_quotes=%s real_fill_requested=%s real_fill_got=%s",
                        CN_PREVIEW_PROVIDER,
                        len(snapshot.data),
                        len(missing),
                        len(extra.data),
                    )
        return bars, CN_PREVIEW_PROVIDER, len(snapshot.data)
    if resolved is Market.US:
        return _collect_us_preview_daily_bars(market_data, wanted, trade_date)
    raise ValueError(f"Preview does not support market {resolved.value}")


def collect_symbol_preview_daily_bars(
    market_data: Any,
    market: Market | str,
    symbols: Iterable[str],
    trade_date: date,
) -> tuple[dict[str, MarketBar], str, int]:
    """CN uses one Tencent real() batch for requested codes; US reuses Yahoo 5m aggregation."""
    resolved = market_from_value(market)
    wanted = tuple(dict.fromkeys(canonical_symbol(symbol) for symbol in symbols))
    if resolved is Market.CN:
        provider = _easyquotation_provider(market_data)
        if provider is None:
            raise PreviewQuoteError("easyquotation tencent unavailable")
        try:
            quotes = provider.fetch_quotes_for_codes(wanted)
        except Exception as exc:
            logger.exception("market=CN provider=%s real_failed requested=%s", CN_PREVIEW_PROVIDER, len(wanted))
            raise PreviewQuoteError(f"easyquotation tencent real failed: {exc}") from exc
        bars: dict[str, MarketBar] = {}
        _bars_from_quotes(quotes, set(wanted), trade_date, bars, converter=close_bar_from_quote)
        if not bars:
            detail = quotes.failed_symbols or "empty quotes"
            raise PreviewQuoteError(f"easyquotation tencent real failed: {detail}")
        logger.info(
            "market=CN provider=%s action=real requested=%s usable=%s",
            CN_PREVIEW_PROVIDER,
            len(wanted),
            len(bars),
        )
        return bars, CN_PREVIEW_PROVIDER, len(bars)
    if resolved is Market.US:
        bars, label, quote_count = _collect_us_preview_daily_bars(market_data, wanted, trade_date)
        if not bars:
            raise PreviewQuoteError("yfinance 5m preview failed: empty bars")
        return bars, label, quote_count
    raise ValueError(f"Preview does not support market {resolved.value}")


__all__ = [
    "CN_PREVIEW_PROVIDER",
    "CN_SNAPSHOT_PROVIDER",
    "PreviewQuoteError",
    "US_PREVIEW_PROVIDER",
    "close_bar_from_quote",
    "collect_preview_daily_bars",
    "collect_symbol_preview_daily_bars",
    "daily_bar_from_quote",
]

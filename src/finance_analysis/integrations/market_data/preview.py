"""Intraday preview bars for Trend Following. Isolated from ordinary provider fallback."""

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
    """Raised when the CN full-market snapshot cannot be used."""


def daily_bar_from_quote(quote: MarketQuote, trade_date: date) -> MarketBar | None:
    prices = (quote.open_price, quote.high, quote.low, quote.price)
    if any(value is None or value <= 0 for value in prices):
        return None
    open_price, high, low, close = (float(quote.open_price), float(quote.high), float(quote.low), float(quote.price))
    if high < max(open_price, close, low) or low > min(open_price, close, high):
        return None
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


def _bars_from_quotes(quotes: Any, wanted: set[str], trade_date: date, bars: dict[str, MarketBar]) -> None:
    for symbol, quote in getattr(quotes, "data", {}).items():
        if symbol not in wanted or symbol in bars:
            continue
        bar = daily_bar_from_quote(quote, trade_date)
        if bar is not None:
            bars[symbol] = bar


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
        _bars_from_quotes(snapshot, wanted_set, trade_date, bars)
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
                    _bars_from_quotes(extra, wanted_set, trade_date, bars)
                    logger.info(
                        "market=CN provider=%s snapshot_quotes=%s real_fill_requested=%s real_fill_got=%s",
                        CN_PREVIEW_PROVIDER,
                        len(snapshot.data),
                        len(missing),
                        len(extra.data),
                    )
        return bars, CN_PREVIEW_PROVIDER, len(snapshot.data)
    if resolved is Market.US:
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
    raise ValueError(f"Trend Following preview does not support market {resolved.value}")


__all__ = [
    "CN_PREVIEW_PROVIDER",
    "CN_SNAPSHOT_PROVIDER",
    "PreviewQuoteError",
    "US_PREVIEW_PROVIDER",
    "collect_preview_daily_bars",
    "daily_bar_from_quote",
]

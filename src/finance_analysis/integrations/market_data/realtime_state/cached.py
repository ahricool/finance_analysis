"""Cache-only display quotes. No provider fallback and no timestamp substitution."""

from datetime import timedelta

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.models import BatchQuoteResult, Market, MarketQuote
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.session import display_day


def display_quote(quote, market, now):
    if (
        quote is None
        or quote.timestamp_kind == "received"
        or quote.trading_date != display_day(market, now)
        or quote.last_price is None
        or quote.last_price <= 0
        or not quote.event_time
        or not quote.received_at
        or quote.event_time > now + timedelta(seconds=5)
        or quote.received_at > now + timedelta(seconds=5)
    ):
        return None
    price, previous = float(quote.last_price), float(quote.pre_close) if quote.pre_close else None
    return MarketQuote(
        symbol=quote.symbol,
        market=Market(market),
        provider=quote.source,
        currency="CNY" if market == "CN" else "USD" if market == "US" else "HKD",
        price=price,
        pre_close=previous,
        change_amount=price - previous if previous else None,
        change_pct=(price / previous - 1) * 100 if previous else None,
        open_price=float(quote.open) if quote.open else None,
        high=float(quote.high) if quote.high else None,
        low=float(quote.low) if quote.low else None,
        volume=quote.volume,
        amount=float(quote.turnover) if quote.turnover is not None else None,
        quote_time=quote.event_time,
    )


def read_cached_quotes(symbols):
    """One Redis round trip for a display batch; a feed outage stays observable."""
    from redis import Redis
    from finance_analysis.integrations.market_data.realtime_state.keys import quote_key
    from finance_analysis.market_stream.config import MarketStreamConfig

    symbols = list(dict.fromkeys(symbols))
    result = BatchQuoteResult()
    if not symbols:
        return result
    now = utc_now()
    with Redis.from_url(
        MarketStreamConfig.from_env().redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
    ) as client:
        pipe = client.pipeline(transaction=False)
        storage_symbols = []
        for symbol in symbols:
            storage = symbol
            if symbol.endswith(".HK"):
                from finance_analysis.integrations.market_data.providers.longbridge.market import _to_longbridge_symbol
                storage = _to_longbridge_symbol(symbol)
            storage_symbols.append(storage)
            pipe.hgetall(quote_key(storage))
        for symbol, storage, raw in zip(symbols, storage_symbols, pipe.execute()):
            market = "US" if symbol.endswith(".US") else "HK" if symbol.endswith(".HK") else "CN"
            state = RealtimeStateRepository._quote_from_mapping(storage, raw) if raw else None
            quote = display_quote(state, market, now)
            if quote is not None:
                from dataclasses import replace
                result.data[symbol] = replace(quote, symbol=symbol)
                result.providers_used[symbol] = quote.provider
            else:
                result.missing_symbols.append(symbol)
    return result

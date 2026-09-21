# -*- coding: utf-8 -*-
"""Market-level account valuation shared by add_v1 and portfolio_risk_v1."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from ..portfolio.models import ResolvedPortfolio, ResolvedPosition  # pragma: allowlist secret
from .models import DailyBar, MarketPortfolioContext, QuoteView, ValuationSource  # pragma: allowlist secret


def quote_usable(quote: QuoteView | None) -> bool:
    return quote is not None and quote.valid and not quote.stale and quote.price is not None


def valuation_price(
    quote: QuoteView | None,
    bars: Sequence[DailyBar],
) -> tuple[Decimal | None, ValuationSource]:
    if quote_usable(quote):
        return quote.price, "QUOTE"
    if bars:
        return bars[-1].close, "DAILY_FALLBACK"
    return None, "UNAVAILABLE"


def build_market_portfolio_context(
    portfolio: ResolvedPortfolio,
    *,
    market: str,
    quotes: Mapping[str, QuoteView],
    daily: Mapping[str, Sequence[DailyBar]],
) -> MarketPortfolioContext:
    positions = portfolio.valuation_positions(market)
    strategy_positions = tuple(item for item in positions if item.trade_engine_eligible)
    cash = portfolio.db_cash(market)
    prices: dict[str, Decimal] = {}
    sources: dict[str, ValuationSource] = {}
    values: dict[str, Decimal] = {}
    incomplete: list[str] = []
    total_value = Decimal("0")
    complete = True
    for position in positions:
        price, source = valuation_price(quotes.get(position.symbol), daily.get(position.symbol, ()))
        sources[position.position_id] = source
        if price is None:
            complete = False
            incomplete.append(position.symbol)
            continue
        value = position.quantity * price
        prices[position.position_id] = price
        values[position.position_id] = value
        total_value += value
    nav = cash + total_value if complete else None
    return MarketPortfolioContext(
        market=market,
        cash=cash,
        positions=positions,
        strategy_positions=strategy_positions,
        valuation_prices=prices,
        valuation_sources=sources,
        market_values=values,
        nav=nav,
        valuation_complete=complete,
        incomplete_symbols=tuple(dict.fromkeys(incomplete)),
    )


def position_value(context: MarketPortfolioContext, position: ResolvedPosition) -> Decimal:
    return context.market_values.get(position.position_id, Decimal("0"))

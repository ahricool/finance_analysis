# -*- coding: utf-8 -*-
"""Quote and completed daily-bar fetch for Trade Engine only."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import Adjustment  # pragma: allowlist secret
from finance_analysis.integrations.market_data.normalizer import infer_market  # pragma: allowlist secret
from finance_analysis.integrations.market_data.service import MarketDataService  # pragma: allowlist secret
from finance_analysis.trade_engine.config import get_risk_policy  # pragma: allowlist secret
from finance_analysis.trade_engine.daily import completed_daily_bars, latest_completed_trading_day  # pragma: allowlist secret
from finance_analysis.trade_engine.models import DailyBar, QuoteView  # pragma: allowlist secret

logger = logging.getLogger(__name__)


class RiskMarketGateway:
    def __init__(
        self,
        *,
        market_data: MarketDataService | None = None,
        quote_max_age_seconds: float | None = None,
    ) -> None:
        self.market_data = market_data or MarketDataService()
        policy = get_risk_policy()
        self.quote_max_age = timedelta(seconds=quote_max_age_seconds or policy.quote_max_age_seconds)

    def quotes(self, symbols: Iterable[str], *, now: datetime | None = None) -> dict[str, QuoteView]:
        current = now or utc_now()
        unique = tuple(dict.fromkeys(symbols))
        if not unique:
            return {}
        by_market: dict = {}
        for symbol in unique:
            by_market.setdefault(infer_market(symbol), []).append(symbol)
        result: dict[str, QuoteView] = {}
        for _market, codes in by_market.items():
            batch = self.market_data.get_realtime_quotes(codes)
            for symbol in codes:
                quote = batch.data.get(symbol)
                if quote is None or quote.price is None:
                    result[symbol] = QuoteView(price=Decimal("0"), quote_as_of=None, valid=False)
                    continue
                quote_time = quote.quote_time
                if quote_time is None:
                    result[symbol] = QuoteView(
                        price=Decimal(str(quote.price)), quote_as_of=None, valid=False, stale=True
                    )
                    continue
                if quote_time > current + timedelta(seconds=5):
                    result[symbol] = QuoteView(
                        price=Decimal(str(quote.price)), quote_as_of=quote_time, valid=False, stale=False
                    )
                    continue
                stale = current - quote_time > self.quote_max_age
                result[symbol] = QuoteView(
                    price=Decimal(str(quote.price)),
                    quote_as_of=quote_time,
                    valid=quote.price > 0 and not stale,
                    stale=stale,
                )
        return result

    def daily_bars(
        self,
        symbols: Iterable[str],
        *,
        start: date,
        end: date,
        now: datetime | None = None,
    ) -> dict[str, list[DailyBar]]:
        current = now or utc_now()
        unique = tuple(dict.fromkeys(symbols))
        if not unique:
            return {}
        try:
            result = self.market_data.get_daily_bars(
                unique,
                start,
                end,
                adjustment=Adjustment.FORWARD,
                source_policy="db_first",
            )
        except Exception:
            logger.exception("trade_engine daily bars failed")
            return {symbol: [] for symbol in unique}
        cutoffs: dict[str, date | None] = {}
        converted: dict[str, list[DailyBar]] = {}
        for symbol in unique:
            market = infer_market(symbol).value
            if market not in cutoffs:
                cutoffs[market] = latest_completed_trading_day(market, current)
            rows = []
            for item in result.data.get(symbol) or []:
                rows.append(
                    DailyBar(
                        trade_date=item.trade_date,
                        open=Decimal(str(item.open)),
                        high=Decimal(str(item.high)),
                        low=Decimal(str(item.low)),
                        close=Decimal(str(item.close)),
                        volume=int(item.volume or 0),
                    )
                )
            converted[symbol] = completed_daily_bars(sorted(rows, key=lambda bar: bar.trade_date), cutoffs[market])
        return converted

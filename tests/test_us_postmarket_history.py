"""Recap reads exercise real DB/provider routing without network or DB writes."""

from datetime import date, timedelta
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.integrations.market_data.models import Adjustment, BatchBarResult, Market, MarketBar
from finance_analysis.integrations.market_data.registry import DAILY_BARS, ProviderRegistry
from finance_analysis.tasks.celery.jobs.us_postmarket_review.history import load_review_history

DAY = date(2026, 6, 23)
SYMBOL = "TSM.US"


def bar(day, close):
    return MarketBar(
        symbol=SYMBOL, market=Market.US, interval="1d", trade_date=day, bar_time=None,
        open=close, high=close, low=close, close=close, volume=100,
        amount=None, currency="USD", adjustment=Adjustment.FORWARD, provider="yfinance",
    )


def market(stored, remote):
    stocks = Mock()
    stocks.get_range.return_value = [
        NS(
            instrument=NS(code=SYMBOL, market="US"), date=b.trade_date,
            open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume, amount=None,
        )
        for b in stored
    ]
    provider = NS(fetch_daily_bars=Mock(return_value=BatchBarResult(data={SYMBOL: remote})))
    registry = ProviderRegistry()
    registry.register("yfinance", provider, capabilities={DAILY_BARS})
    service = MarketDataService(registry, instrument_repository=NS(), stock_repository=stocks)
    return service, stocks, provider


def test_fresh_db_is_used_without_provider_requests():
    service, stocks, provider = market([bar(DAY - timedelta(days=1), 100), bar(DAY, 110)], [])
    frame, source = load_review_history(SYMBOL, target_date=DAY, market_data=service)
    assert source == "database"
    assert frame.iloc[-1].pct_chg == pytest.approx(10)
    provider.fetch_daily_bars.assert_not_called()
    assert {call[0] for call in stocks.method_calls} == {"get_range"}


@pytest.mark.parametrize("stored", [[], [bar(DAY - timedelta(days=1), 1000)], [bar(DAY, 1000)]])
def test_missing_stale_or_short_db_uses_whole_provider_window_without_writes(stored):
    service, stocks, provider = market(stored, [bar(DAY - timedelta(days=1), 100), bar(DAY, 110)])
    frame, source = load_review_history(SYMBOL, target_date=DAY, market_data=service)
    assert source == "yfinance"
    assert list(frame.close) == [100, 110]  # Do not mix incompatible adjustment scales with DB's 1000.
    assert frame.iloc[-1].pct_chg == pytest.approx(10)
    request = provider.fetch_daily_bars.call_args.args[0]
    assert request.symbols == (SYMBOL,) and request.end_date == DAY
    assert request.adjustment == Adjustment.FORWARD
    assert {call[0] for call in stocks.method_calls} == {"get_range"}


@pytest.mark.parametrize("remote", [[], [bar(DAY - timedelta(days=1), 100)], [bar(DAY, 110)]])
def test_incomplete_provider_data_is_not_reported_as_target_day_performance(remote):
    service, _, _ = market([], remote)
    with pytest.raises(RuntimeError, match="Recap daily data unavailable"):
        load_review_history(SYMBOL, target_date=DAY, market_data=service)


def test_future_provider_bars_are_excluded():
    service, _, _ = market(
        [], [bar(DAY - timedelta(days=1), 100), bar(DAY, 110), bar(DAY + timedelta(days=1), 120)]
    )
    frame, _ = load_review_history(SYMBOL, target_date=DAY, market_data=service)
    assert frame.iloc[-1].date == DAY and frame.iloc[-1].close == 110


def test_default_recap_loader_uses_provider_fallback():
    from finance_analysis.tasks.celery.jobs.us_postmarket_review.domain_service import USPostmarketReviewService

    service, _, _ = market([], [bar(DAY - timedelta(days=1), 100), bar(DAY, 110)])
    recap = USPostmarketReviewService(config=NS(), db=NS(), market_data_service=service)
    performance = recap._fetch_daily_performance(SYMBOL, "TSM", DAY)
    assert performance.close == 110 and performance.change_pct == pytest.approx(10)
    assert performance.source == "yfinance"

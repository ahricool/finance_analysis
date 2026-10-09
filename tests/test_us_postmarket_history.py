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


def add_fallback(service, bars=None, *, error=None, request_error=None):
    from dataclasses import replace

    response = BatchBarResult(
        data={SYMBOL: [replace(item, provider="tickflow") for item in (bars or [])]},
        request_errors={SYMBOL: request_error} if request_error else {},
    )
    provider = NS(fetch_daily_bars=Mock(return_value=response, side_effect=error))
    service.registry.register("tickflow", provider, capabilities={DAILY_BARS})
    return provider


@pytest.mark.parametrize("primary", [
    [bar(DAY - timedelta(days=1), 1000)],
    [bar(DAY, 1000)],
    [bar(DAY - timedelta(days=4), 900), bar(DAY, 1000)],
])
def test_partial_primary_falls_back_to_whole_complete_provider_series(primary):
    service, stocks, first = market([bar(DAY - timedelta(days=1), 2000)], primary)
    second = add_fallback(service, [bar(DAY - timedelta(days=1), 100), bar(DAY, 110)])

    frame, source = load_review_history(SYMBOL, target_date=DAY, market_data=service)

    assert source == "tickflow"
    assert list(frame.close) == [100, 110]
    assert frame.iloc[-1].pct_chg == pytest.approx(10)
    assert set(frame.provider) == {"tickflow"}
    first.fetch_daily_bars.assert_called_once()
    second.fetch_daily_bars.assert_called_once()
    first_request = first.fetch_daily_bars.call_args.args[0]
    second_request = second.fetch_daily_bars.call_args.args[0]
    assert second_request == first_request
    assert set(second_request.required_dates) == {DAY - timedelta(days=1), DAY}
    assert {call[0] for call in stocks.method_calls} == {"get_range"}


@pytest.mark.parametrize("first_error", [False, True])
def test_complete_fallback_clears_primary_request_error(first_error):
    service, stocks, first = market([], [])
    if first_error:
        first.fetch_daily_bars.side_effect = RuntimeError("primary unavailable")
    else:
        first.fetch_daily_bars.return_value = BatchBarResult(
            data={SYMBOL: [bar(DAY - timedelta(days=1), 100)]},
            request_errors={SYMBOL: "partial response"},
        )
    second = add_fallback(service, [bar(DAY - timedelta(days=1), 100), bar(DAY, 110)])
    result = service.get_daily_bars(
        [SYMBOL], DAY - timedelta(days=5), DAY, adjustment="forward", source_policy="db_latest",
        required_dates=[DAY - timedelta(days=1), DAY],
    )
    assert result.providers_used == {SYMBOL: "tickflow"}
    assert not result.request_errors and not result.failed_symbols and not result.missing_symbols
    second.fetch_daily_bars.assert_called_once()
    assert {call[0] for call in stocks.method_calls} == {"get_range"}


@pytest.mark.parametrize("mode", ["incomplete", "exception", "reported_error"])
def test_no_complete_provider_fails_without_stitching_sources(mode):
    service, stocks, first = market([], [bar(DAY - timedelta(days=1), 1000)])
    second = add_fallback(
        service,
        [bar(DAY, 110)] if mode == "incomplete" else [bar(DAY - timedelta(days=1), 100), bar(DAY, 110)],
        error=RuntimeError("fallback unavailable") if mode == "exception" else None,
        request_error="partial response" if mode == "reported_error" else None,
    )
    with pytest.raises(RuntimeError, match="Recap daily data unavailable") as exc:
        load_review_history(SYMBOL, target_date=DAY, market_data=service)
    assert "yfinance" in str(exc.value) and "tickflow" in str(exc.value)
    first.fetch_daily_bars.assert_called_once()
    second.fetch_daily_bars.assert_called_once()
    assert {call[0] for call in stocks.method_calls} == {"get_range"}


def test_database_error_still_uses_date_aware_provider_fallback():
    service, stocks, first = market([], [bar(DAY - timedelta(days=1), 1000)])
    stocks.get_range.side_effect = RuntimeError("DB unavailable")
    second = add_fallback(service, [bar(DAY - timedelta(days=1), 100), bar(DAY, 110)])
    frame, source = load_review_history(SYMBOL, target_date=DAY, market_data=service)
    assert source == "tickflow" and list(frame.close) == [100, 110]
    first.fetch_daily_bars.assert_called_once()
    second.fetch_daily_bars.assert_called_once()


def test_default_nonempty_daily_routing_remains_unchanged():
    service, _, first = market([], [bar(DAY - timedelta(days=1), 1000)])
    second = add_fallback(service, [bar(DAY - timedelta(days=1), 100), bar(DAY, 110)])
    result = service.get_daily_bars(
        [SYMBOL], DAY - timedelta(days=5), DAY, adjustment="forward", source_policy="remote_only",
    )
    assert result.providers_used == {SYMBOL: "yfinance"}
    first.fetch_daily_bars.assert_called_once()
    second.fetch_daily_bars.assert_not_called()


def test_all_provider_exceptions_are_reported():
    service, _, first = market([], [])
    first.fetch_daily_bars.side_effect = RuntimeError("primary unavailable")
    second = add_fallback(service, error=RuntimeError("fallback unavailable"))
    with pytest.raises(RuntimeError, match="Recap daily data unavailable") as exc:
        load_review_history(SYMBOL, target_date=DAY, market_data=service)
    assert "yfinance: primary unavailable" in str(exc.value)
    assert "tickflow: fallback unavailable" in str(exc.value)
    second.fetch_daily_bars.assert_called_once()


def test_required_dates_fallback_is_per_symbol_in_a_batch():
    from dataclasses import replace

    other = "AAPL.US"
    service, _, first = market([], [bar(DAY - timedelta(days=1), 1000)])
    first.fetch_daily_bars.return_value.data[other] = [
        replace(item, symbol=other) for item in [bar(DAY - timedelta(days=1), 200), bar(DAY, 220)]
    ]
    second = add_fallback(service, [bar(DAY - timedelta(days=1), 100), bar(DAY, 110)])
    result = service.get_daily_bars(
        [SYMBOL, other], DAY - timedelta(days=5), DAY, adjustment="forward", source_policy="remote_only",
        required_dates=[DAY - timedelta(days=1), DAY],
    )
    assert result.providers_used == {SYMBOL: "tickflow", other: "yfinance"}
    assert second.fetch_daily_bars.call_args.args[0].symbols == (SYMBOL,)
    assert [item.close for item in result.data[SYMBOL]] == [100, 110]
    assert [item.close for item in result.data[other]] == [200, 220]


@pytest.mark.parametrize("policy", ["db_only", "db_first", "db_fresh"])
def test_required_dates_rejects_policies_that_cannot_enforce_single_source_completeness(policy):
    service, stocks, first = market([], [])
    with pytest.raises(ValueError, match="required_dates requires"):
        service.get_daily_bars(
            [SYMBOL], DAY - timedelta(days=1), DAY, adjustment="forward", source_policy=policy,
            required_dates=[DAY],
        )
    first.fetch_daily_bars.assert_not_called()
    assert not stocks.method_calls


def test_required_dates_must_be_inside_requested_window():
    service, stocks, first = market([], [])
    with pytest.raises(ValueError, match="required_dates must be within"):
        service.get_daily_bars(
            [SYMBOL], DAY - timedelta(days=1), DAY, adjustment="forward", source_policy="db_latest",
            required_dates=[DAY + timedelta(days=1)],
        )
    first.fetch_daily_bars.assert_not_called()
    assert not stocks.method_calls

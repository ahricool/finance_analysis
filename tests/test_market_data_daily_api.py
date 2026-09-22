"""Daily chart API contract using the real service/router and offline repositories."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.integrations.market_data.models import Adjustment, BatchBarResult, Market, MarketBar
from finance_analysis.integrations.market_data.registry import DAILY_BARS, ProviderRegistry
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.market_data import service as market_service
from finance_analysis.interfaces.api.v1.endpoints import market_data


@pytest.fixture
def setup_api(monkeypatch):
    monkeypatch.setattr(market_service, "utc_now", lambda: datetime(2026, 9, 20, tzinfo=timezone.utc))
    monkeypatch.setattr(market_data, "utc_now", lambda: datetime(2026, 9, 20, tzinfo=timezone.utc))
    instruments = Mock()
    instruments.get_by_code.return_value = SimpleNamespace(id=1)
    stocks = Mock()
    stocks.has_daily_data.return_value = False
    stocks.get_range.return_value = []
    provider = Mock()
    registry = ProviderRegistry()
    registry.register("daily", provider, capabilities={DAILY_BARS})
    service = MarketDataService(registry, instrument_repository=instruments, stock_repository=stocks)
    # Keep the production router, fixing only the offline test registry's provider list.
    route = service.router.route_daily
    service.router.route_daily = lambda request, providers=None: route(request, ["daily"])
    monkeypatch.setattr(market_data, "MarketDataService", lambda: service)
    app = FastAPI()
    app.include_router(market_data.router, prefix="/api/v1/market-data")
    return TestClient(app), stocks, provider


def bar(code="600519.SH", day=date(2026, 9, 18)):
    return MarketBar(code, Market.US if code.endswith('.US') else Market.CN, "1d", day, None,
                     100, 105, 98, 103, 123456, 123456789, "CNY", Adjustment.FORWARD, "daily")


def test_database_data_never_calls_provider(setup_api):
    client, stocks, provider = setup_api
    stocks.has_daily_data.return_value = True
    stocks.get_range.return_value = [SimpleNamespace(
        instrument=SimpleNamespace(code="600519.SH", market="CN"), date=date(2026, 9, 18),
        open=100, high=105, low=98, close=103, volume=123456, amount=123456789,
    )]
    response = client.get('/api/v1/market-data/daily-bars/600519.SH?start_date=2026-09-01&end_date=2026-09-18')
    assert response.status_code == 200
    assert response.json()['source'] == 'database'
    assert response.json()['adjustment'] == 'forward'
    stocks.get_range.assert_called_once_with('600519.SH', date(2026, 9, 1), date(2026, 9, 18))
    provider.fetch_daily_bars.assert_not_called()
    stocks.upsert_daily.assert_not_called()


@pytest.mark.parametrize('raw,code,market', [('sh600519', '600519.SH', 'CN'), ('aapl', 'AAPL.US', 'US')])
@pytest.mark.parametrize('db_error', [False, True])
def test_empty_or_failed_database_falls_back(setup_api, raw, code, market, db_error, caplog):
    client, stocks, provider = setup_api
    if db_error:
        stocks.get_range.side_effect = RuntimeError('database offline')
    provider.fetch_daily_bars.return_value = BatchBarResult(data={code: [bar(code)]})
    response = client.get(f'/api/v1/market-data/daily-bars/{raw}?start_date=2026-09-01&end_date=2026-09-18')
    assert response.status_code == 200
    value = response.json()
    assert (value['symbol'], value['market'], value['source'], value['interval']) == (code, market, 'daily', '1d')
    assert value['items'][0]['trade_date'] == '2026-09-18'
    request = provider.fetch_daily_bars.call_args.args[0]
    assert request.start_date == date(2026, 9, 1)
    assert request.end_date == date(2026, 9, 18)
    assert request.adjustment is Adjustment.FORWARD
    stocks.upsert_daily.assert_not_called()
    if db_error:
        assert 'falling back' in caplog.text


def test_provider_failure_is_503(setup_api):
    client, stocks, provider = setup_api
    stocks.get_range.side_effect = RuntimeError('database offline')
    provider.fetch_daily_bars.side_effect = RuntimeError('provider offline')
    response = client.get('/api/v1/market-data/daily-bars/AAPL.US')
    assert response.status_code == 503
    assert 'provider offline' not in response.text


def test_empty_invalid_dates_and_default_window(setup_api):
    client, _, provider = setup_api
    provider.fetch_daily_bars.return_value = BatchBarResult()
    assert client.get('/api/v1/market-data/daily-bars/AAPL?start_date=bad').status_code == 422
    assert client.get('/api/v1/market-data/daily-bars/AAPL?start_date=2026-09-19&end_date=2026-09-18').status_code == 422
    provider.fetch_daily_bars.assert_not_called()
    response = client.get('/api/v1/market-data/daily-bars/AAPL?end_date=2026-09-18')
    assert response.json()['items'] == []
    request = provider.fetch_daily_bars.call_args.args[0]
    assert (request.end_date - request.start_date).days == 365


def test_recovered_data_ignores_sticky_errors_and_excludes_future(setup_api):
    client, _, provider = setup_api
    provider.fetch_daily_bars.return_value = BatchBarResult(
        data={'600519.SH': [bar(), bar(day=date(2026, 9, 19))]},
        request_errors={'600519.SH': 'earlier provider failed'},
    )
    response = client.get('/api/v1/market-data/daily-bars/600519.SH?end_date=2026-09-18')
    assert response.status_code == 200
    assert [row['trade_date'] for row in response.json()['items']] == ['2026-09-18']


@pytest.fixture
def realtime_api(setup_api, monkeypatch):
    from finance_analysis.integrations.market_data.registry import REALTIME_QUOTES

    client, stocks, daily = setup_api
    service = market_data.MarketDataService()
    providers = {name: Mock() for name in ('fuyao', 'yfinance', 'longbridge')}
    for name, provider in providers.items():
        service.registry.register(name, provider, capabilities={REALTIME_QUOTES})
    now = datetime(2026, 9, 21, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(market_data, 'utc_now', lambda: now)
    monkeypatch.setattr(market_service, 'utc_now', lambda: now)
    return client, stocks, daily, providers


def realtime_quote(code, provider, **changes):
    from finance_analysis.integrations.market_data.models import BatchQuoteResult, MarketQuote

    fields = dict(symbol=code, market=Market.US if code.endswith('.US') else Market.CN,
                  provider=provider, currency='USD' if code.endswith('.US') else 'CNY',
                  open_price=103, high=110, low=100, price=108, volume=123, amount=13284,
                  quote_time=datetime(2026, 9, 21, 15, tzinfo=timezone.utc))
    fields.update(changes)
    return BatchQuoteResult(data={code: MarketQuote(**fields)})


@pytest.mark.parametrize('code,primary', [('600519.SH', 'fuyao'), ('AAPL.US', 'yfinance')])
@pytest.mark.parametrize('failure', [None, 'exception', 'missing', 'stale', 'invalid'])
def test_intraday_provider_order_and_validation(realtime_api, code, primary, failure):
    from finance_analysis.integrations.market_data.models import BatchQuoteResult

    client, stocks, daily, providers = realtime_api
    daily.fetch_daily_bars.return_value = BatchBarResult(data={code: [bar(code)]})
    providers[primary].fetch_quotes.return_value = realtime_quote(code, primary)
    if failure == 'exception':
        providers[primary].fetch_quotes.side_effect = RuntimeError('offline')
    elif failure == 'missing':
        providers[primary].fetch_quotes.return_value = BatchQuoteResult()
    elif failure == 'stale':
        providers[primary].fetch_quotes.return_value = realtime_quote(
            code, primary, quote_time=datetime(2026, 9, 18, 15, tzinfo=timezone.utc))
    elif failure == 'invalid':
        providers[primary].fetch_quotes.return_value = realtime_quote(code, primary, high=101)
    providers['longbridge'].fetch_quotes.return_value = realtime_quote(code, 'longbridge')
    response = client.get(f'/api/v1/market-data/daily-bars/{code}?end_date=2026-09-21')
    assert response.status_code == 200
    assert [row['trade_date'] for row in response.json()['items']] == ['2026-09-18', '2026-09-21']
    assert response.json()['items'][-1] == dict(
        trade_date='2026-09-21', open=103, high=110, low=100, close=108, volume=123, amount=13284)
    providers[primary].fetch_quotes.assert_called_once()
    assert providers['longbridge'].fetch_quotes.call_count == (1 if failure else 0)
    providers['yfinance' if primary == 'fuyao' else 'fuyao'].fetch_quotes.assert_not_called()
    stocks.upsert_daily.assert_not_called()


@pytest.mark.parametrize('changes', [
    {'quote_time': datetime(2026, 9, 18, 15, tzinfo=timezone.utc)},
    {'quote_time': None}, {'quote_time': datetime(2026, 9, 21, 15)},
    {'open_price': None}, {'price': float('nan')}, {'high': float('inf')},
    {'low': 109}, {'open_price': 0}, {'volume': None},
])
def test_unusable_quotes_do_not_create_today(realtime_api, changes):
    client, _, daily, providers = realtime_api
    code = '600519.SH'
    daily.fetch_daily_bars.return_value = BatchBarResult(data={code: [bar(code)]})
    for name in ('fuyao', 'longbridge'):
        providers[name].fetch_quotes.return_value = realtime_quote(code, name, **changes)
    response = client.get(f'/api/v1/market-data/daily-bars/{code}?end_date=2026-09-21')
    assert response.status_code == 200
    assert [row['trade_date'] for row in response.json()['items']] == ['2026-09-18']


def test_both_quote_providers_fail_open(realtime_api):
    client, _, daily, providers = realtime_api
    daily.fetch_daily_bars.return_value = BatchBarResult(data={'AAPL.US': [bar('AAPL.US')]})
    for provider in providers.values():
        provider.fetch_quotes.side_effect = RuntimeError('offline')
    response = client.get('/api/v1/market-data/daily-bars/AAPL.US?end_date=2026-09-21')
    assert response.status_code == 200
    assert len(response.json()['items']) == 1
    providers['yfinance'].fetch_quotes.assert_called_once()
    providers['longbridge'].fetch_quotes.assert_called_once()


@pytest.mark.parametrize('code,now,query', [
    ('600519.SH', '2026-09-21T03:00:00+00:00', '?end_date=2026-09-18'),
    ('600519.SH', '2026-09-21T03:00:00+00:00', '?start_date=2026-09-22&end_date=2026-09-23'),
    ('600519.SH', '2026-09-20T03:00:00+00:00', ''),
    ('600519.SH', '2026-10-01T03:00:00+00:00', ''),
    ('AAPL.US', '2026-09-07T15:00:00+00:00', ''),
    ('AAPL.US', '2026-09-21T01:00:00+00:00', ''),  # Sunday in New York
    ('00700.HK', '2026-09-21T03:00:00+00:00', ''),
])
def test_outside_today_or_nontrading_day_skips_quotes(realtime_api, monkeypatch, code, now, query):
    client, _, daily, providers = realtime_api
    monkeypatch.setattr(market_data, 'utc_now', lambda: datetime.fromisoformat(now))
    daily.fetch_daily_bars.return_value = BatchBarResult()
    response = client.get(f'/api/v1/market-data/daily-bars/{code}{query}')
    assert response.status_code == 200
    assert response.json()['items'] == []
    for provider in providers.values():
        provider.fetch_quotes.assert_not_called()


@pytest.mark.parametrize('code,primary,now', [
    ('600519.SH', 'fuyao', '2026-09-20T16:30:00+00:00'),
    ('AAPL.US', 'yfinance', '2026-09-22T00:30:00+00:00'),
])
def test_market_date_default_and_existing_today_replaced(realtime_api, monkeypatch, code, primary, now):
    client, stocks, daily, providers = realtime_api
    now = datetime.fromisoformat(now)
    monkeypatch.setattr(market_data, 'utc_now', lambda: now)
    daily.fetch_daily_bars.return_value = BatchBarResult(data={code: [bar(code, date(2026, 9, 21)), bar(code)]})
    providers[primary].fetch_quotes.return_value = realtime_quote(code, primary, quote_time=now)
    response = client.get(f'/api/v1/market-data/daily-bars/{code}')
    assert response.status_code == 200
    rows = response.json()['items']
    assert [row['trade_date'] for row in rows] == ['2026-09-18', '2026-09-21']
    assert rows[-1]['close'] == 108
    assert daily.fetch_daily_bars.call_args.args[0].end_date == date(2026, 9, 21)
    stocks.upsert_daily.assert_not_called()


def test_today_overlay_keeps_database_freshness_and_no_sync(realtime_api):
    client, stocks, daily, providers = realtime_api
    stocks.has_daily_data.return_value = True
    stocks.get_range.return_value = [SimpleNamespace(
        instrument=SimpleNamespace(code='AAPL.US', market='US'), date=date(2026, 9, 18),
        open=100, high=105, low=98, close=103, volume=123456, amount=None,
    )]
    providers['yfinance'].fetch_quotes.return_value = realtime_quote('AAPL.US', 'yfinance')
    response = client.get('/api/v1/market-data/daily-bars/AAPL.US?end_date=2026-09-21')
    assert response.status_code == 200
    assert response.json()['source'] == 'database'
    assert [row['trade_date'] for row in response.json()['items']] == ['2026-09-18', '2026-09-21']
    stocks.get_range.assert_called_once_with('AAPL.US', date(2025, 9, 21), date(2026, 9, 21))
    daily.fetch_daily_bars.assert_not_called()
    stocks.upsert_daily.assert_not_called()

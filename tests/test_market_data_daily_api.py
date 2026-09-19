"""Daily chart API contract using the real service/router and offline repositories."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.integrations.market_data.models import Adjustment, BatchBarResult, Market, MarketBar
from finance_analysis.integrations.market_data.registry import DAILY_BARS, ProviderRegistry
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.interfaces.api.v1.endpoints import market_data


@pytest.fixture
def setup_api(monkeypatch):
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
        stocks.has_daily_data.side_effect = RuntimeError('database offline')
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
    stocks.has_daily_data.side_effect = RuntimeError('database offline')
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

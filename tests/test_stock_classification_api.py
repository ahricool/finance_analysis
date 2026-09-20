from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.v1.endpoints import stocks


@pytest.fixture
def client(monkeypatch):
    instruments = Mock()
    universes = Mock()
    monkeypatch.setattr(stocks, "InstrumentRepository", lambda: instruments)
    monkeypatch.setattr(stocks, "UniverseRepository", lambda: universes)
    # Classification must never use the external market-data facade.
    monkeypatch.setattr(stocks, "MarketDataService", Mock(side_effect=AssertionError("database only")))
    app = FastAPI()
    app.include_router(stocks.router, prefix="/api/v1/stocks")
    with TestClient(app) as http:
        yield http, instruments, universes


@pytest.mark.parametrize(
    "code, market, indices",
    [
        ("NVDA.US", "US", [
            {"key": "us_nasdaq100", "name": "Nasdaq 100", "source": "WIKIPEDIA"},
            {"key": "us_sp500", "name": "S&P 500", "source": "WIKIPEDIA"},
        ]),
        ("600519.SH", "CN", [{"key": "cn_csi300", "name": "沪深300", "source": "AKSHARE"}]),
        ("OTHER.US", "US", []),
    ],
)
def test_classification_response(client, code, market, indices):
    http, instruments, universes = client
    instruments.get_by_code.return_value = SimpleNamespace(code=code, market=market)
    universes.list_index_memberships.return_value = indices
    response = http.get(f"/api/v1/stocks/{code}/classification")
    assert response.status_code == 200
    assert response.json() == {"code": code, "market": market, "memberships": {"indices": indices}}
    instruments.get_by_code.assert_called_once_with(code)
    universes.list_index_memberships.assert_called_once_with(code)


def test_classification_unknown_stock(client):
    http, instruments, universes = client
    instruments.get_by_code.return_value = None
    response = http.get("/api/v1/stocks/UNKNOWN.US/classification")
    assert response.status_code == 404
    universes.list_index_memberships.assert_not_called()


def test_classification_invalid_code_matches_stock_info(client):
    http, instruments, _ = client
    response = http.get("/api/v1/stocks/INVALID.SH/classification")
    assert response.status_code == 422
    assert response.json() == http.get("/api/v1/stocks/INVALID.SH/info").json()
    instruments.get_by_code.assert_not_called()

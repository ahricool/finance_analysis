from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.endpoints import backtests


def make_client(user=None):
    app = FastAPI()
    app.include_router(backtests.router, prefix="/api/v1/backtests")
    app.dependency_overrides[require_current_user] = lambda: user or SimpleNamespace(id=7, role="user")
    return TestClient(app)


def test_engine_api_is_ordered_and_backtrader_is_default():
    response = make_client().get("/api/v1/backtests/engines")
    assert response.status_code == 200
    engines = response.json()
    assert [item["key"] for item in engines] == ["backtrader", "rqalpha"]
    assert engines[0]["is_default"] is True
    assert engines[1]["supported_markets"] == ["CN"]


def test_strategy_api_filters_by_real_engine_market_capabilities():
    client = make_client()
    assert [item["key"] for item in client.get(
        "/api/v1/backtests/strategies", params={"engine": "backtrader", "market": "US"}
    ).json()] == ["sma_cross"]
    assert client.get(
        "/api/v1/backtests/strategies", params={"engine": "rqalpha", "market": "US"}
    ).json() == []
    parameter = client.get(
        "/api/v1/backtests/strategies", params={"engine": "rqalpha", "market": "CN"}
    ).json()[0]["parameters"][0]
    assert parameter == {
        "key": "fast_window", "name": "快均线周期", "type": "integer",
        "default": 5, "minimum": 2, "maximum": 120,
    }


def test_symbol_api_applies_engine_and_market_before_repository(monkeypatch):
    calls = []

    class FakeSymbols:
        def search_enabled_symbols(self, market, keyword, limit):
            calls.append((market, keyword, limit))
            return [SimpleNamespace(id=1, market="US", code="AAPL.US", name="Apple", lot_size=None)]

    monkeypatch.setattr(backtests, "MarketDataSymbolRepository", FakeSymbols)
    client = make_client()
    assert client.get("/api/v1/backtests/symbols", params={
        "engine": "rqalpha", "market": "US", "keyword": "AAPL",
    }).json() == []
    response = client.get("/api/v1/backtests/symbols", params={
        "engine": "backtrader", "market": "US", "keyword": "AAPL",
    })
    assert response.status_code == 200
    assert response.json()[0]["code"] == "AAPL.US"
    assert calls == [("US", "AAPL", 30)]


def test_run_detail_scopes_repository_query_to_current_user(monkeypatch):
    calls = []

    class FakeRepo:
        def get_run(self, run_id, *, uid, is_admin):
            calls.append((run_id, uid, is_admin))
            return None

    monkeypatch.setattr(backtests, "BacktestRepository", FakeRepo)
    response = make_client(SimpleNamespace(id=42, role="user")).get("/api/v1/backtests/runs/99")
    assert response.status_code == 404
    assert calls == [(99, 42, False)]


def test_preflight_api_rejects_invalid_sma_parameters_before_submission(monkeypatch):
    class FakeService:
        def preflight(self, values):
            from finance_analysis.backtest.strategies.registry import get_strategy

            get_strategy(values["strategy_key"]).validate_parameters(values["parameters"])

    monkeypatch.setattr(backtests, "BacktestService", FakeService)
    response = make_client().post(
        "/api/v1/backtests/preflight",
        json={
            "engine": "backtrader", "strategy_key": "sma_cross", "market": "US", "code": "AAPL.US",
            "start_date": date(2025, 1, 1).isoformat(), "end_date": date(2025, 2, 1).isoformat(),
            "parameters": {"fast_window": 20, "slow_window": 5},
        },
    )
    assert response.status_code == 400
    assert "fast_window" in response.json()["detail"]

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.endpoints import intraday_options, market_data
from tests.intraday_options.test_scoring import START
from tests.market_stream.fakes import FakeRedis


def test_snapshot_contract_requires_auth_and_never_fetches_remote(monkeypatch):
    app = FastAPI()
    app.include_router(intraday_options.router, prefix="/api/v1/intraday-options")
    repo = RealtimeStateRepository(FakeRedis())
    monkeypatch.setattr(intraday_options.RealtimeStateRepository, "from_url", lambda url: repo)
    monkeypatch.setattr(intraday_options, "load_names", lambda: {})
    monkeypatch.setattr(intraday_options, "utc_now", lambda: START)
    with TestClient(app) as client:
        assert client.get("/api/v1/intraday-options").status_code == 401
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(uid=1)
        response = client.get("/api/v1/intraday-options")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        body = response.json()
        assert len(body["items"]) == 30
        assert body["items"][7]["symbol"] == "SPCX.US"
        assert body["items"][7]["data_status"] == "waiting"
        assert body["items"][7]["result"] is None


def test_shared_pool_chart_does_not_require_personal_watchlist(monkeypatch):
    repo = RealtimeStateRepository(FakeRedis())
    monkeypatch.setattr(market_data.RealtimeStateRepository, "from_url", lambda url: repo)
    monkeypatch.setattr(market_data, "get_effective_uid", lambda request: 1)
    monkeypatch.setattr(market_data, "utc_now", lambda: START)

    def forbidden(*args, **kwargs):
        raise AssertionError("must not read personal tracking or fetch a provider")

    monkeypatch.setattr(market_data, "_load_tracked_stocks", forbidden)
    monkeypatch.setattr(market_data, "MarketDataService", forbidden)
    result = asyncio.run(market_data.intraday_bars("SPCX.US", SimpleNamespace()))
    assert result["symbol"] == "SPCX.US" and result["items"] == []

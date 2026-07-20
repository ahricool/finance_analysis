from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.endpoints import quant as quant_endpoint


class FakeQuantRepository:
    def __init__(self):
        self.calls = []

    def get_universe(self, key):
        self.calls.append(("get_universe", key))
        market = "CN" if key == "cn_csi300_watchlist" else "US"
        return SimpleNamespace(id=2 if market == "CN" else 1, key=key, market=market)

    def latest_signals(self, market, universe_id=None, code=None):
        self.calls.append(("latest_signals", market, universe_id, code))
        return []

    def market_regimes(self, *args, **kwargs):
        return []

    def signal_history(self, market, code):
        self.calls.append(("signal_history", market, code))
        return []

    def sector_regimes(self, market, trade_date=None, sector_key=None):
        self.calls.append(("sector_regimes", market, trade_date, sector_key))
        return [SimpleNamespace(market=market, trade_date=date(2026, 7, 17), sector_key="电子")]


def _client(monkeypatch):
    repository = FakeQuantRepository()
    monkeypatch.setattr(quant_endpoint, "QuantRepository", lambda: repository)
    app = FastAPI()
    app.include_router(quant_endpoint.router, prefix="/quant")
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    return TestClient(app), repository


def test_signal_ranking_uses_cn_default_universe_and_market_filter(monkeypatch):
    client, repository = _client(monkeypatch)

    response = client.get("/quant/signals/ranking?market=CN")

    assert response.status_code == 200
    assert response.json()["market"] == "CN"
    assert response.json()["universe"] == "cn_csi300_watchlist"
    assert ("latest_signals", "CN", 2, None) in repository.calls


def test_quant_api_rejects_unsupported_market_and_scopes_signal_history(monkeypatch):
    client, repository = _client(monkeypatch)

    assert client.get("/quant/signals/ranking?market=HK").status_code == 422
    response = client.get("/quant/signals/600519.SH/history?market=CN")

    assert response.status_code == 200
    assert ("signal_history", "CN", "600519.SH") in repository.calls


def test_sector_ranking_without_date_delegates_latest_market_only_query(monkeypatch):
    client, repository = _client(monkeypatch)

    response = client.get("/quant/sectors/ranking?market=CN")

    assert response.status_code == 200
    assert response.json()[0]["market"] == "CN"
    assert ("sector_regimes", "CN", None, None) in repository.calls

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.endpoints import quant as quant_endpoint
from finance_analysis.quant.markets import validate_universe_for_market


class FakeQuantRepository:
    def __init__(self):
        self.calls = []

    def get_universe(self, key):
        self.calls.append(("get_universe", key))
        if key == 99:
            return SimpleNamespace(
                id=99,
                key="us_ai_semiconductor",
                market="US",
                enabled=False,
            )
        market = "CN" if key == "cn_csi300_watchlist" else "US"
        return SimpleNamespace(id=2 if market == "CN" else 1, key=key, market=market, enabled=True)

    def supported_universe(self, market, key=None):
        return self.get_universe(validate_universe_for_market(market, key))

    def get_model_run(self, run_id):
        return SimpleNamespace(id=run_id, market="US", universe_id=99)

    def list_universes(self, market):
        self.calls.append(("list_universes", market))
        supported = self.get_universe(
            "cn_csi300_watchlist" if market == "CN" else "us_sp500_watchlist"
        )
        deprecated = SimpleNamespace(
            id=99,
            key="us_ai_semiconductor",
            market="US",
            enabled=False,
        )
        return [supported, deprecated] if market == "US" else [supported]

    def active_members(self, universe_id, trade_date):
        return []

    def latest_signals(self, market, universe_id=None, code=None):
        self.calls.append(("latest_signals", market, universe_id, code))
        return []

    def market_regimes(self, *args, **kwargs):
        return []

    def list_model_runs(self, market=None, universe_id=None):
        self.calls.append(("list_model_runs", market, universe_id))
        return []

    def list_datasets(self, market=None, universe_id=None):
        self.calls.append(("list_datasets", market, universe_id))
        return []

    def latest_portfolios(self, market, universe_id=None):
        self.calls.append(("latest_portfolios", market, universe_id))
        return []

    def signal_history(self, market, code, universe_id=None):
        self.calls.append(("signal_history", market, code, universe_id))
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
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1)
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
    assert ("signal_history", "CN", "600519.SH", 2) in repository.calls


def test_sector_ranking_without_date_delegates_latest_market_only_query(monkeypatch):
    client, repository = _client(monkeypatch)

    response = client.get("/quant/sectors/ranking?market=CN")

    assert response.status_code == 200
    assert response.json()[0]["market"] == "CN"
    assert ("sector_regimes", "CN", None, None) in repository.calls


def test_quant_api_rejects_deprecated_and_cross_market_universes(monkeypatch):
    client, _ = _client(monkeypatch)

    deprecated = client.get(
        "/quant/signals/ranking?market=US&universe=us_ai_semiconductor"
    )
    cross_market = client.get(
        "/quant/signals/ranking?market=CN&universe=us_sp500_watchlist"
    )

    assert deprecated.status_code == 409
    assert "deprecated" in deprecated.json()["detail"]
    assert "us_sp500_watchlist" in deprecated.json()["detail"]
    assert cross_market.status_code == 409
    assert "cn_csi300_watchlist" in cross_market.json()["detail"]


def test_universe_list_exposes_only_the_market_supported_universe(monkeypatch):
    client, _ = _client(monkeypatch)

    us = client.get("/quant/universes?market=US")
    cn = client.get("/quant/universes?market=CN")

    assert us.status_code == 200
    assert [item["key"] for item in us.json()] == ["us_sp500_watchlist"]
    assert cn.status_code == 200
    assert [item["key"] for item in cn.json()] == ["cn_csi300_watchlist"]


def test_normal_model_dataset_and_portfolio_lists_filter_the_supported_universe(monkeypatch):
    client, repository = _client(monkeypatch)

    assert client.get("/quant/models?market=CN").status_code == 200
    assert client.get("/quant/datasets?market=CN").status_code == 200
    assert client.get("/quant/portfolios?market=CN").status_code == 200

    assert ("list_model_runs", "CN", 2) in repository.calls
    assert ("list_datasets", "CN", 2) in repository.calls
    assert ("latest_portfolios", "CN", 2) in repository.calls


def test_dataset_and_model_write_endpoints_reject_deprecated_universe(monkeypatch):
    client, _ = _client(monkeypatch)

    dataset = client.post(
        "/quant/datasets/build",
        json={
            "market": "US",
            "universe": "us_ai_semiconductor",
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
        },
    )
    model = client.post(
        "/quant/model-runs",
        json={
            "market": "US",
            "universe": "us_ai_semiconductor",
            "model_version": "deprecated-test",
            "dataset_snapshot_id": 1,
        },
    )
    publication = client.post(
        "/quant/model-runs/9/publish?market=US",
        json={"reason": "verify deprecation rejection"},
    )

    assert dataset.status_code == 409
    assert model.status_code == 409
    assert publication.status_code == 409
    assert all("deprecated" in response.json()["detail"] for response in (dataset, model, publication))

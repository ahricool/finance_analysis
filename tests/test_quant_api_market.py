from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.endpoints import quant as quant_endpoint
from finance_analysis.interfaces.api.v1.schemas.quant import ModelRunCreateRequest
from finance_analysis.quant.markets import validate_universe_for_market


class FakeQuantRepository:
    def __init__(self):
        self.calls = []
        self.created_model_run = None
        self.model_run_updates = []

    def get_universe(self, key):
        self.calls.append(("get_universe", key))
        if key == 99:
            return SimpleNamespace(
                id=99,
                key="us_ai_semiconductor",
                market="US",
                enabled=False,
            )
        market = "CN" if key == "cn_csi300" else "US"
        return SimpleNamespace(id=2 if market == "CN" else 1, key=key, market=market, enabled=True)

    def supported_universe(self, market, key=None):
        return self.get_universe(validate_universe_for_market(market, key))

    def get_model_run(self, run_id):
        return SimpleNamespace(id=run_id, market="US", universe_id=99)

    def list_model_definitions(self):
        common = {
            "model_type": "cross_section",
            "task_type": "regression",
            "frequency": "day",
            "supported_markets": ["US", "CN"],
        }
        return [
            SimpleNamespace(id=1, key="cross_section_lgbm", name="Cross section", enabled=True, **common),
            SimpleNamespace(id=2, key="time_series_lgbm", name="Time series", enabled=True, **common),
            SimpleNamespace(id=3, key="cross_section_ridge", name="Ridge", enabled=True, **common),
            SimpleNamespace(id=4, key="disabled_lgbm", name="Disabled", enabled=False, **common),
        ]

    def get_model_definition(self, key):
        return next((item for item in self.list_model_definitions() if item.key == key), None)

    def get_dataset(self, snapshot_id):
        return SimpleNamespace(
            id=snapshot_id,
            market="US",
            universe_id=1,
            status="ready",
            artifact_uri="quant://datasets/us-ready",
            price_mode="forward_adjusted",
        )

    def create_model_run(self, values):
        self.created_model_run = values
        return SimpleNamespace(id=77)

    def update_model_run(self, run_id, **values):
        self.model_run_updates.append((run_id, values))

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
    assert response.json()["universe"] == "cn_csi300"
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


def test_quant_api_rejects_unsupported_and_cross_market_universes(monkeypatch):
    client, _ = _client(monkeypatch)

    unsupported = client.get(
        "/quant/signals/ranking?market=US&universe=us_ai_semiconductor"
    )
    cross_market = client.get(
        "/quant/signals/ranking?market=CN&universe=us_sp500"
    )

    assert unsupported.status_code == 409
    assert "only supported universe is us_sp500" in unsupported.json()["detail"]
    assert cross_market.status_code == 409
    assert "cn_csi300" in cross_market.json()["detail"]


def test_universe_list_exposes_only_the_market_supported_universe(monkeypatch):
    client, _ = _client(monkeypatch)

    us = client.get("/quant/universes?market=US")
    cn = client.get("/quant/universes?market=CN")

    assert us.status_code == 200
    assert [item["key"] for item in us.json()] == ["us_sp500"]
    assert cn.status_code == 200
    assert [item["key"] for item in cn.json()] == ["cn_csi300"]


def test_normal_model_dataset_and_portfolio_lists_filter_the_supported_universe(monkeypatch):
    client, repository = _client(monkeypatch)

    assert client.get("/quant/models?market=CN").status_code == 200
    assert client.get("/quant/datasets?market=CN").status_code == 200
    assert client.get("/quant/portfolios?market=CN").status_code == 200

    assert ("list_model_runs", "CN", 2) in repository.calls
    assert ("list_datasets", "CN", 2) in repository.calls
    assert ("latest_portfolios", "CN", 2) in repository.calls


def test_model_definitions_expose_only_worker_trainable_models(monkeypatch):
    client, _ = _client(monkeypatch)

    response = client.get("/quant/models/definitions?market=CN")

    assert response.status_code == 200
    assert {item["key"] for item in response.json()} == {
        "cross_section_lgbm",
        "time_series_lgbm",
    }


def test_model_run_defaults_match_worker_contract_and_dispatch_explicit_run(monkeypatch):
    client, repository = _client(monkeypatch)
    from finance_analysis.tasks.celery.jobs.quant_training import tasks as training_tasks

    apply_async = MagicMock(return_value=SimpleNamespace(id="training-task-1"))
    monkeypatch.setattr(training_tasks.train_quant_model, "apply_async", apply_async)

    response = client.post(
        "/quant/model-runs",
        json={
            "market": "US",
            "model_key": "cross_section_lgbm",
            "model_version": "us-cross-section-20260721",
            "dataset_snapshot_id": 5,
        },
    )

    assert response.status_code == 202
    assert response.json()["model_run_id"] == 77
    assert repository.created_model_run["target_config"]["benchmark"] == "sector_or_market"
    assert repository.created_model_run["split_config"]["prediction_horizon"] == 5
    apply_async.assert_called_once_with(
        kwargs={"model_run_id": 77, "owner_uid": 1},
        queue="analysis",
    )
    assert repository.model_run_updates[-1] == (77, {"task_id": "training-task-1"})


def test_model_run_rejects_legacy_raw_dataset(monkeypatch):
    client, repository = _client(monkeypatch)
    original = repository.get_dataset

    def raw_dataset(snapshot_id):
        dataset = original(snapshot_id)
        dataset.price_mode = "raw"
        return dataset

    repository.get_dataset = raw_dataset
    response = client.post(
        "/quant/model-runs",
        json={
            "market": "US",
            "model_key": "cross_section_lgbm",
            "model_version": "legacy-raw-rejected",
            "dataset_snapshot_id": 5,
        },
    )

    assert response.status_code == 409
    assert "forward_adjusted" in response.json()["detail"]
    assert repository.created_model_run is None


def test_model_run_request_rejects_worker_incompatible_configuration():
    with pytest.raises(ValidationError, match="prediction_horizon must match"):
        ModelRunCreateRequest(
            model_version="bad-horizon",
            dataset_snapshot_id=5,
            split_config={"prediction_horizon": 5},
            target_config={"prediction_horizon": 10},
        )

    with pytest.raises(ValidationError, match="String should match pattern"):
        ModelRunCreateRequest(model_version="../escape", dataset_snapshot_id=5)


def test_model_run_dispatch_failure_marks_created_run_failed(monkeypatch):
    client, repository = _client(monkeypatch)
    from finance_analysis.tasks.celery.jobs.quant_training import tasks as training_tasks

    monkeypatch.setattr(
        training_tasks.train_quant_model,
        "apply_async",
        MagicMock(side_effect=RuntimeError("broker unavailable")),
    )

    response = client.post(
        "/quant/model-runs",
        json={
            "market": "US",
            "model_key": "time_series_lgbm",
            "model_version": "us-time-series-20260721",
            "dataset_snapshot_id": 5,
        },
    )

    assert response.status_code == 503
    assert repository.model_run_updates[-1][0] == 77
    assert repository.model_run_updates[-1][1]["status"] == "failed"
    assert repository.model_run_updates[-1][1]["progress"] == 100


def test_dataset_and_model_write_endpoints_reject_unsupported_universe(monkeypatch):
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
            "model_version": "unsupported-test",
            "dataset_snapshot_id": 1,
        },
    )
    publication = client.post(
        "/quant/model-runs/9/publish?market=US",
        json={"reason": "verify unsupported universe rejection"},
    )

    assert dataset.status_code == 409
    assert model.status_code == 409
    assert publication.status_code == 409
    assert all("only supported universe" in response.json()["detail"] for response in (dataset, model, publication))

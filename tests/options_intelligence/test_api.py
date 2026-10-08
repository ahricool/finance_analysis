from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from finance_analysis.interfaces.api.v1.endpoints import options_intelligence as api
from finance_analysis.interfaces.api.deps import require_current_user, require_admin


@pytest.fixture
def client(repository, monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/options-intelligence")
    user = SimpleNamespace(id=7, role="user")
    app.dependency_overrides[require_current_user] = lambda: user

    def no_admin():
        raise HTTPException(403, "Administrator required")

    app.dependency_overrides[require_admin] = no_admin
    monkeypatch.setattr(api, "OptionsRepository", lambda: repository)
    yield TestClient(app)


def test_detail_read_does_not_fetch_missing_options(client):
    response = client.get("/api/v1/options-intelligence/AAPL.US")
    assert response.status_code == 200
    assert response.json()["latest"] is None
    assert response.json()["events"] == []


def test_scan_passes_effective_uid(client, repository):
    seen = []
    repository.monitored_symbols = lambda defaults, uid: seen.append(uid) or ["AAPL.US"]
    assert client.get("/api/v1/options-intelligence").json()["items"][0]["status"] == "not_scanned"
    assert seen == [7]


def test_run_is_admin_only_and_bad_symbols_are_rejected(client):
    assert client.post("/api/v1/options-intelligence/run", json={}).status_code == 403
    assert client.get("/api/v1/options-intelligence/600519.SH").status_code == 422
    assert client.post("/api/v1/options-intelligence/AAPL.US/explain").status_code == 409


def test_refresh_is_explicit_asynchronous_and_attributed(client, monkeypatch):
    from finance_analysis.tasks.celery.jobs.options_intelligence.tasks import options_request

    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id="test-options-task")

    monkeypatch.setattr(options_request, "apply_async", send)
    response = client.post("/api/v1/options-intelligence/AAPL.US/refresh")
    assert response.status_code == 202
    assert response.json()["task_id"] == "test-options-task"
    assert calls[0]["kwargs"]["_triggered_by_uid"] == 7
    assert calls[0]["kwargs"]["owner_uid"] == 7
    assert calls[0]["kwargs"]["symbol"] == "AAPL.US"
    assert calls[0]["queue"] == "ingestion"

from types import SimpleNamespace
from unittest.mock import Mock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from finance_analysis.interfaces.api.v1.endpoints import options_intelligence as api
from finance_analysis.interfaces.api.deps import require_current_user, require_admin


@pytest.fixture
def client(repository, monkeypatch):
    from finance_analysis.database.models import Instrument

    with repository.db.get_session() as session:
        Instrument.__table__.create(session.get_bind())
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/options-intelligence")
    user = SimpleNamespace(id=7, role="user")
    app.dependency_overrides[require_current_user] = lambda: user

    def no_admin():
        raise HTTPException(403, "Administrator required")

    app.dependency_overrides[require_admin] = no_admin
    monkeypatch.setattr(api, "OptionsRepository", lambda: repository)
    monkeypatch.setattr(api, "load_preview", lambda **kwargs: None)
    yield TestClient(app)


def test_detail_read_does_not_fetch_missing_options(client):
    response = client.get("/api/v1/options-intelligence/AAPL.US")
    assert response.status_code == 200
    assert response.json()["latest"] is None
    assert response.json()["events"] == []


def test_scan_passes_effective_uid(client, repository):
    seen = []
    repository.monitored_symbols = lambda uid: seen.append(uid) or ["AAPL.US"]
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


def test_preview_list_filters_other_users_watch_symbols_and_has_no_official_fallback(client, repository, monkeypatch):
    repository.monitored_symbols = lambda uid: ["AAPL.US", "FAIL.US"]
    monkeypatch.setattr(
        api,
        "load_preview",
        lambda: {
            "trade_date": "2026-10-07",
            "items": [
                {"symbol": "AAPL.US", "status": "ready", "event_types": ["PUT_VOLUME_SPIKE"]},
                {"symbol": "PRIVATE.US", "status": "ready"},
            ],
            "failures": [
                {"symbol": "FAIL.US", "reason": "provider unavailable"},
                {"symbol": "PRIVATE.US", "reason": "private failure"},
            ],
        },
    )
    response = client.get("/api/v1/options-intelligence?view=preview").json()
    assert [r["symbol"] for r in response["items"]] == ["AAPL.US", "FAIL.US"]
    assert response["items"][0]["event_types"] == ["PUT_VOLUME_SPIKE"]
    assert response["items"][1]["status"] == "failed" and response["failed_count"] == 1
    assert response["view"] == "preview"
    monkeypatch.setattr(api, "load_preview", lambda: None)
    response = client.get("/api/v1/options-intelligence?view=preview").json()
    assert response["items"] == [] and response["reason"]


def test_detail_selected_date_does_not_mix_latest_or_future_history(
    client, repository, observation, now, config, monkeypatch
):
    from .test_repository import save
    from datetime import timedelta
    from finance_analysis.integrations.market_data.service import MarketDataService

    monkeypatch.setattr(MarketDataService, "get_daily_bars", lambda *args, **kwargs: SimpleNamespace(data={}))

    save(repository, observation, now, config)
    date = now.date().isoformat()
    response = client.get(f"/api/v1/options-intelligence/AAPL.US?trade_date={date}").json()
    assert response["trade_date"] == date and response["latest"]["trade_date"] == date
    before = (now.date() - timedelta(days=1)).isoformat()
    response = client.get(f"/api/v1/options-intelligence/AAPL.US?trade_date={before}").json()
    assert response["latest"] is None and response["events"] == [] and response["daily_history"] == []
    assert client.get("/api/v1/options-intelligence/AAPL.US?trade_date=invalid").status_code == 422
    assert client.get("/api/v1/options-intelligence/AAPL.US?view=invalid").status_code == 422


def test_refresh_passes_requested_storage_view(client, monkeypatch):
    from finance_analysis.tasks.celery.jobs.options_intelligence.tasks import options_request

    send = Mock(return_value=SimpleNamespace(id="preview-task"))
    monkeypatch.setattr(options_request, "apply_async", send)
    assert client.post("/api/v1/options-intelligence/AAPL.US/refresh", json={"view": "preview"}).status_code == 202
    assert send.call_args.kwargs["kwargs"]["view"] == "preview"


@pytest.mark.parametrize("view", ["official", "preview"])
def test_scan_names_use_one_master_data_lookup_without_mutating_evidence(client, repository, monkeypatch, view):
    from copy import deepcopy
    from finance_analysis.database.repositories.stock import InstrumentRepository

    instruments = InstrumentRepository(repository.db)
    instruments.upsert_symbols([
        {"code": "NVDA.US", "market": "US", "name": "NVIDIA Corporation"},
        {"code": "AAPL.US", "market": "US", "name": "苹果"},
        {"code": "MSFT.US", "market": "US", "name": "Microsoft Corporation"},
        {"code": "PRIVATE.US", "market": "US", "name": "Other user's stock"},
    ])
    visible = ["NVDA.US", "AAPL.US", "MSFT.US", "UNKNOWN.US"]
    repository.monitored_symbols = lambda uid: visible
    rows = [
        {"symbol": "NVDA.US", "name": "stale snapshot label", "status": "ready", "scores": None},
        {"symbol": "AAPL.US", "status": "failed", "scores": None, "limitations": ["provider timeout"]},
        {"symbol": "MSFT.US", "status": "not_scanned", "scores": None},
        {"symbol": "UNKNOWN.US", "status": "not_scanned", "scores": None},
    ]
    repository.scan = lambda *args, **kwargs: rows
    payload = {
        "trade_date": "2026-10-07",
        "items": [rows[0], {"symbol": "PRIVATE.US", "status": "ready"}],
        "failures": [{"symbol": "AAPL.US", "reason": "provider timeout"}],
    }
    original_rows, original_payload = deepcopy(rows), deepcopy(payload)
    monkeypatch.setattr(api, "load_preview", lambda: payload)
    lookups = []
    original_lookup = InstrumentRepository.names_by_codes

    def names_by_codes(self, codes):
        lookups.append(list(codes))
        return original_lookup(self, lookups[-1])

    monkeypatch.setattr(InstrumentRepository, "names_by_codes", names_by_codes)
    response = client.get(f"/api/v1/options-intelligence?view={view}&trade_date=2026-10-07")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [(row["symbol"], row["name"]) for row in items] == [
        ("NVDA.US", "NVIDIA Corporation"), ("AAPL.US", "苹果"),
        ("MSFT.US", "Microsoft Corporation"), ("UNKNOWN.US", None),
    ]
    assert [row["status"] for row in items] == ["ready", "failed", "not_scanned", "not_scanned"]
    assert lookups == [visible]
    assert rows == original_rows and payload == original_payload


def test_empty_preview_skips_name_lookup(client, repository, monkeypatch):
    repository.monitored_symbols = lambda uid: ["AAPL.US"]
    lookup = Mock(side_effect=AssertionError("empty preview must not query instrument names"))
    monkeypatch.setattr(api.InstrumentRepository, "names_by_codes", lookup)
    response = client.get("/api/v1/options-intelligence?view=preview")
    assert response.status_code == 200 and response.json()["items"] == []
    lookup.assert_not_called()

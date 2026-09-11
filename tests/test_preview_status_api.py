"""Preview status reads existing cache metadata without exposing strategy rows."""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.v1.endpoints import etf_rotation, trend_following


@pytest.mark.parametrize("endpoint,rows_key", [(trend_following, "snapshots"), (etf_rotation, "items")])
@pytest.mark.parametrize("status", ["completed", "failed", "incomplete"])
def test_status_reads_cache_once_and_only_returns_metadata(monkeypatch, endpoint, rows_key, status):
    payload = {
        "status": status, "market": "CN", "trade_date": "2026-09-11",
        "preview_time": "2026-09-11T06:00:00Z", "data_as_of": "2026-09-11T05:59:00Z",
        "provider": "easyquotation_tencent", "warnings": [] if status == "completed" else ["not ready"],
        rows_key: [{"code": "TEST", "features": {"large": [1] * 100}}] * 3794,
        "features": {"large": [2] * 100}, "score_breakdown": {"private_to_full_payload": True},
    }
    original = deepcopy(payload)
    calls = []
    monkeypatch.setattr(endpoint, "load_preview", lambda market: calls.append(market) or payload)
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.require_current_user] = lambda: None
    with TestClient(app) as client:
        response = client.get("/preview/status?market=CN")
    assert response.status_code == 200
    assert response.json() == {**{key: payload[key] for key in (
        "status", "market", "trade_date", "preview_time", "data_as_of", "provider", "warnings",
    )}, "snapshot_count": 3794}
    assert len(response.content) < 400
    assert calls == ["CN"]
    assert payload == original
    # Existing full endpoint and cache shape remain intact.
    assert endpoint.preview(None, "CN") == original


@pytest.mark.parametrize("endpoint", [trend_following, etf_rotation])
def test_status_missing_preview_preserves_404(monkeypatch, endpoint):
    monkeypatch.setattr(endpoint, "load_preview", lambda market: None)
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.require_current_user] = lambda: None
    with TestClient(app) as client:
        assert client.get("/preview/status?market=US").status_code == 404
        assert client.get("/preview?market=US").status_code == 404

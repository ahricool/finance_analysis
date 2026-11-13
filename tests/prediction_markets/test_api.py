from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.v1.endpoints import prediction_markets as api
from finance_analysis.interfaces.api.deps import require_current_user, require_admin
from finance_analysis.prediction_markets.config import Config


def test_get_dynamic_does_not_write_enqueue_or_call_llm_and_admin_permission(monkeypatch):
    writes = []

    class Repo:
        def event(self, event_id):
            return dict(retained=True)

        def set_tag(self, *args):
            writes.append(args)

    class Live:
        def live(self, event_id):
            return dict(status="ready", markets=[])

        def history(self, *args):
            raise ValueError("unrelated")

    monkeypatch.setattr(api, "get_config", lambda: Config(enabled=True))
    monkeypatch.setattr(api, "get_live_service", lambda: Live())
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.repository] = lambda: Repo()
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)

    def denied():
        raise HTTPException(403)

    app.dependency_overrides[require_admin] = denied
    c = TestClient(app)
    assert c.get("/events/1/live").json()["status"] == "ready"
    assert c.get("/events/1/history", params=dict(market_id="1", outcome_id="x")).status_code == 422
    assert c.patch("/admin/tags/1", json={"visible": True}).status_code == 403
    assert not writes
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1)
    assert c.patch("/admin/tags/1", json={"visible": True}).status_code == 200
    assert writes == [("1", True)]
    monkeypatch.setattr(api, "get_config", lambda: Config())
    assert c.get("/events/1/live").json()["status"] == "disabled"
    assert c.get("/events").json()["status"] == "disabled"

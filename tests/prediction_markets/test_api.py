from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.v1.endpoints import prediction_markets as api
from finance_analysis.interfaces.api.deps import require_current_user


def test_stock_search_read_only_and_removed_routes(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "search_stock", lambda symbol, name: calls.append((symbol, name)) or dict(status="ready"))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.instruments] = lambda: SimpleNamespace(
        get_by_code=lambda code: SimpleNamespace(name="NVIDIA")
    )
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    c = TestClient(app)
    assert c.get("/stocks/NVDA.US").status_code == 200
    assert calls == [("NVDA.US", "NVIDIA")]
    for url in ["/events", "/tags", "/admin/tags", "/admin/events"]:
        assert c.get(url).status_code == 404
    assert c.post("/admin/run", json={"job": "catalog"}).status_code == 404
    assert c.get("/events/not-an-id/live").status_code == 422

    def denied():
        raise HTTPException(401)

    app.dependency_overrides[require_current_user] = denied
    assert c.get("/stocks/NVDA.US").status_code == 401


def test_dynamic_get_checks_outcome_membership_without_catalog(monkeypatch):
    class Live:
        def live(self, event_id):
            return dict(status="ready", markets=[])

        def history(self, *args):
            raise ValueError("unrelated")

    monkeypatch.setattr(api, "get_live_service", lambda: Live())
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    c = TestClient(app)
    assert c.get("/events/1/live").json()["status"] == "ready"
    assert c.get("/events/1/history", params=dict(market_id="1", outcome_id="x")).status_code == 422


def test_no_catalog_tables_or_tasks():
    from finance_analysis.database.base import Base
    import finance_analysis.database.models  # noqa: F401
    from finance_analysis.tasks.celery.schedule import get_scheduled_task_definitions

    assert not {"prediction_event", "prediction_tag"} & Base.metadata.tables.keys()
    assert not any("polymarket" in d.job_id for d in get_scheduled_task_definitions())

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


def test_matching_and_stock_surfaces_are_removed(monkeypatch):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1)
    monkeypatch.setattr(api, "get_config", lambda: Config(enabled=True))
    client = TestClient(app)
    assert client.get("/stocks/NVDA.US").status_code == 404
    assert client.put("/admin/events/1/links", json={"symbol": "NVDA.US", "action": "add"}).status_code == 404
    assert client.post("/admin/run", json={"job": "matching"}).status_code == 422


def test_catalog_task_does_not_schedule_followup_or_use_llm(monkeypatch):
    from finance_analysis.tasks.celery.jobs.polymarket import tasks
    from finance_analysis.llm import LLMClient
    from finance_analysis.tasks.celery.schedule import get_scheduled_task_definitions

    def forbidden(*args, **kwargs):
        raise AssertionError("Catalog must not invoke LLM or enqueue another task")

    calls = []
    monkeypatch.setattr(LLMClient, "complete_text", forbidden)
    monkeypatch.setattr(tasks.celery_app, "send_task", forbidden)
    monkeypatch.setattr(tasks, "get_config", lambda: Config(enabled=True))
    monkeypatch.setattr(
        tasks,
        "Service",
        lambda: SimpleNamespace(
            catalog=lambda slug: calls.append(slug) or {"status": "completed"},
            client=SimpleNamespace(close=lambda: calls.append("closed")),
        ),
    )
    # Exercise the task body without the database-backed lifecycle wrapper.
    assert tasks.polymarket_catalog_sync.run.__wrapped__(slug="example") == {"status": "completed"}
    assert calls == ["example", "closed"]
    assert not hasattr(tasks, "polymarket_stock_matching")
    assert [d.job_id for d in get_scheduled_task_definitions() if d.job_id.startswith("polymarket_")] == [
        "polymarket_catalog_sync"
    ]

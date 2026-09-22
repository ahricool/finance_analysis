from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.endpoints import signal_center as api
from finance_analysis.tasks.celery.jobs.signal_center import tasks
from finance_analysis.tasks.lifecycle import TaskSkipped
from finance_analysis.tasks.celery.schedule.registry import build_task_routes, require_scheduled_task_definition


def test_reads_are_authenticated_paginated_and_never_rebuild_history():
    calls = []
    repo = SimpleNamespace(get=lambda m, d: calls.append((m, d)), history=lambda limit, offset: [])
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_repository] = lambda: repo
    client = TestClient(app)
    assert client.get("/history").status_code in (401, 403)
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    assert client.get("/daily?signal_date=2026-09-22").json() == {
        "items": [],
        "requested_dates": {"CN": "2026-09-22", "US": "2026-09-22"},
    }
    assert calls == [("CN", date(2026, 9, 22)), ("US", date(2026, 9, 22))]
    assert client.get("/CN/2026-09-22").status_code == 404
    assert client.get("/HK/2026-09-22").status_code == 422
    assert client.get("/history?limit=101").status_code == 422
    assert client.get("/history?offset=-1").status_code == 422
    assert client.get("/history").json() == []


@pytest.mark.parametrize("market,zone,hour", [("CN", "Asia/Shanghai", 21), ("US", "America/New_York", 23)])
def test_tasks_check_readiness_then_deadline_and_use_market_local_date(monkeypatch, market, zone, hour):
    calls = []
    service = SimpleNamespace(run=lambda m, d, **kw: calls.append((m, d, kw)) or {"status": "completed"})
    monkeypatch.setattr(tasks, "SignalCenterService", lambda: service)
    for minute, expected in [(40, False), (50, True)]:
        monkeypatch.setattr(
            tasks, "get_market_now", lambda *_: datetime(2026, 9, 22, hour, minute, tzinfo=ZoneInfo(zone))
        )
        tasks._run(market)
        assert calls[-1] == (market, date(2026, 9, 22), {"deadline": expected})
    definition = require_scheduled_task_definition(f"signal_center_{market.lower()}")
    assert definition.timezone == zone
    assert build_task_routes()[definition.celery_task_name] == {"queue": "analysis"}


def test_intraday_and_weekend_do_not_read_sources(monkeypatch):
    monkeypatch.setattr(tasks, "SignalCenterService", lambda: pytest.fail("must not construct service"))
    for now in [
        datetime(2026, 9, 22, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        datetime(2026, 9, 26, 22, tzinfo=ZoneInfo("Asia/Shanghai")),
    ]:
        monkeypatch.setattr(tasks, "get_market_now", lambda *_: now)
        with pytest.raises(TaskSkipped):
            tasks._run("CN")


def test_history_includes_separate_typed_evaluation_without_mutating_analysis(monkeypatch):
    from datetime import timezone
    from finance_analysis.signal_center import evaluation

    monkeypatch.setattr(evaluation, "utc_now", lambda: datetime(2026, 9, 23, 12, tzinfo=timezone.utc))
    saved = dict(
        market="US",
        signal_date="2026-09-18",
        status="completed",
        decision="BUY",
        selected_symbol="TEST.US",
        confidence="high",
        created_at="2026-09-19T03:00:00Z",
        completed_at="2026-09-19T03:20:00Z",
    )
    queries = []
    repo = SimpleNamespace(
        history=lambda *_: [saved],
        load_evaluation_bars=lambda pairs: queries.append(pairs)
        or [dict(code=code, date=day, open=100, high=120, low=90, close=110, volume=10) for code, day in pairs],
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_repository] = lambda: repo
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    response = TestClient(app).get("/history")
    assert response.status_code == 200
    result = response.json()[0]
    assert "evaluation" not in saved
    assert len(queries) == 1
    assert result["evaluation"]["entry_date"] == "2026-09-21"
    assert result["evaluation"]["horizons"][0]["value"] == pytest.approx(0.1)
    assert result["evaluation"]["horizons"][1]["status"] == "pending"

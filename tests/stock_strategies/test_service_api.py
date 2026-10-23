from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.endpoints import stock_strategies as api
from finance_analysis.stock_strategies.features import DataNotReady
from finance_analysis.stock_strategies.registry import STRATEGIES
from finance_analysis.stock_strategies.service import StockStrategyService
from .helpers import inputs

NOW = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)  # New York22:00 on19th


@contextmanager
def lock(_market):
    yield SimpleNamespace(acquired=True)


class Loader:
    def __init__(self):
        self.loads = []

    def freeze(self, market):
        return dict(stocks=["A.US", "B.US"], etfs=[], breadth=["A.US", "B.US"], instruments={}, hash="frozen")

    def load(self, market, day, universe, anchor_dates=()):
        self.loads.append(day)
        return inputs(day)


def test_failure_isolated_shared_window_success_not_rerun_and_retry(repository, monkeypatch):
    from finance_analysis.stock_strategies import service as module

    original = module.advance
    failed = True

    def evaluate(spec, *args):
        if failed and spec.key == STRATEGIES[0].key:
            raise ValueError("intentional strategy failure")
        return original(spec, *args)

    monkeypatch.setattr(module, "advance", evaluate)
    loader = Loader()
    service = StockStrategyService(repository, loader, (STRATEGIES[0], STRATEGIES[2]), lock)
    result = service.run("US", now=NOW)
    assert result["failed"] == 1 and result["success"] == 1
    assert len(loader.loads) == 1
    assert repository.latest(STRATEGIES[0], "US")[1]["reason"] == "intentional strategy failure"
    assert repository.latest(STRATEGIES[2], "US")[0]["nav"] == 1e6
    failed = False
    result = service.run("US", now=NOW)
    assert result["failed"] == 0 and result["success"] == 1
    assert len(repository.curve(STRATEGIES[2], "US")) == 1
    assert repository.latest(STRATEGIES[0], "US")[1]["status"] == "success"


def test_waiting_does_not_start_a_different_simulation_date(repository):
    loader = Loader()
    loader.load = lambda *a, **kw: (_ for _ in ()).throw(DataNotReady("waiting daily"))
    service = StockStrategyService(repository, loader, (STRATEGIES[0],), lock)
    assert service.run("US", now=NOW)["waiting"] == 1
    state = repository.state(STRATEGIES[0], "US")
    assert state["start_date"].isoformat() == "2026-10-19" and state["last_date"] is None
    assert service.overview("US")["items"][0]["status"] == "waiting"


def test_views_validate_contract_and_get_never_initializes_ledger(repository):
    service = StockStrategyService(repository, Loader(), lock_factory=lock)
    app = FastAPI()
    app.include_router(api.router, prefix="/strategies")
    app.dependency_overrides[api.get_service] = lambda: service
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        response = client.get("/strategies?market=US")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 6
        assert response.json()["items"][0]["status"] == "not_started"
        assert repository.state(STRATEGIES[0], "US") is None
        assert client.get("/strategies/ma_dd30?market=CN").status_code == 404
        assert client.get("/strategies?market=HK").status_code == 422
        service.run("US", STRATEGIES[0].key, now=NOW)
        response = client.get("/strategies/ma_dd30?market=US")
        assert response.status_code == 200, response.text
        assert response.json()["latest"]["payload"]["plan"]["execution_date"] == "2026-10-20"
        assert response.json()["curve"][0]["benchmark_return"] == 0
        assert response.json()["universe"]["hash"] == "frozen"
        assert client.get("/strategies/ma_dd30?market=US&limit=999").status_code == 422
        assert client.post("/strategies/run", json={"market": "US"}).status_code in (401, 403)


def test_run_requires_admin_and_dispatches_only_the_single_task(repository, monkeypatch):
    from finance_analysis.tasks.celery.jobs.stock_strategies.tasks import run_stock_strategies

    recorded = []
    monkeypatch.setattr(
        run_stock_strategies, "apply_async", lambda **kw: recorded.append(kw) or SimpleNamespace(id="task")
    )
    app = FastAPI()
    app.include_router(api.router, prefix="/strategies")
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        assert (
            client.post("/strategies/run", json={"market": "US", "strategy_key": "hybrid_breakout"}).status_code == 422
        )
        assert (
            client.post("/strategies/run", json={"market": "US", "strategy_key": "ma_dd30"}).json()["task_id"] == "task"
        )
    assert recorded[0]["kwargs"]["strategy_key"] == "ma_dd30"
    assert recorded[0]["queue"] == "analysis"


def test_daytime_recovery_settles_waiting_day_without_advancing_to_today(repository):
    loader = Loader()
    healthy_load = loader.load
    loader.load = lambda *a, **kw: (_ for _ in ()).throw(DataNotReady("waiting daily"))
    service = StockStrategyService(repository, loader, (STRATEGIES[0],), lock)
    assert service.run("US", now=NOW)["waiting"] == 1
    loader.load = healthy_load
    daytime = datetime(2026, 10, 20, 14, tzinfo=timezone.utc)
    result = service.run("US", now=daytime)
    assert result["success"] == 1 and result["waiting"] == 0
    latest, attempt, _, _ = repository.latest(STRATEGIES[0], "US")
    assert latest["trade_date"].isoformat() == "2026-10-19"
    assert attempt["status"] == "success"
    assert latest["payload"]["next_is_historical"] is True
    assert latest["payload"]["computed_at"] == daytime.isoformat()
    assert service.run("US", now=daytime)["results"] == []


def test_catchup_date_respects_market_window_weekends_and_holidays(repository, monkeypatch):
    cases = [
        ("CN", "2026-10-23T04:00:00+00:00", "2026-10-22"),
        ("CN", "2026-10-23T08:00:00+00:00", "2026-10-22"),
        ("CN", "2026-10-23T11:00:00+00:00", "2026-10-23"),
        ("CN", "2026-10-26T04:00:00+00:00", "2026-10-23"),
        ("CN", "2026-10-01T04:00:00+00:00", "2026-09-30"),
        ("US", "2026-10-23T16:00:00+00:00", "2026-10-22"),
        ("US", "2026-10-23T21:00:00+00:00", "2026-10-22"),
        ("US", "2026-10-24T02:00:00+00:00", "2026-10-23"),
    ]
    service = StockStrategyService(repository, Loader(), lock_factory=lock)
    observed = []
    monkeypatch.setattr(service, "_market", lambda market, day, *args: observed.append(day.isoformat()) or [])
    for market, now, expected in cases:
        service.run(market, now=datetime.fromisoformat(now))
        assert observed[-1] == expected, (market, now)

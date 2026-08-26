from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from finance_analysis.interfaces.api.v1.endpoints import etf_rotation
from finance_analysis.tasks.celery.jobs import TASK_MODULES
from finance_analysis.tasks.celery.schedule import (
    JOB_ETF_ROTATION_CN,
    build_beat_schedule,
    require_scheduled_task_definition,
)


def _snapshot(code="588000.SH"):
    return {
        "id": 1,
        "trade_date": date(2026, 8, 25),
        "symbol_id": 1,
        "code": code,
        "entry_score": 88.0,
        "momentum_score": 80.0,
        "generated_at": datetime(2026, 8, 25, 10, 40, tzinfo=timezone.utc),
    }


class FakeRepository:
    def latest_trade_date(self):
        return date(2026, 8, 25)

    def snapshots_by_date(self, trade_date, *, sort_by="entry_score"):
        assert trade_date == date(2026, 8, 25)
        assert sort_by == "entry_score"
        return [_snapshot()]

    def daily_codes_on_date(self, codes, trade_date):
        assert trade_date == date(2026, 8, 25)
        return set(codes)

    def candidates_by_date(self, trade_date, *, limit=5):
        return [_snapshot()][:limit]

    def snapshot_history(self, code, *, limit=60):
        assert code == "588000.SH"
        return [_snapshot(code)][:limit]

    def available_trade_dates(self):
        return [date(2026, 8, 25), date(2026, 8, 24)]


def test_ranking_candidates_and_detail_use_rotation_repository(monkeypatch) -> None:
    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", FakeRepository)
    user = SimpleNamespace(id=1)
    ranking = asyncio.run(etf_rotation.ranking(None, "entry_score", None, user))
    candidates = asyncio.run(etf_rotation.candidates(None, 5, user))
    detail = asyncio.run(etf_rotation.detail("588000.SH", 60, user))
    assert ranking["items"][0]["name"] == "科创50ETF"
    assert ranking["universe_size"] == 40
    assert candidates["items"][0]["code"] == "588000.SH"
    assert detail["metadata"]["theme"] == "STAR50"
    assert detail["latest"]["code"] == "588000.SH"


def test_ranking_uses_requested_trade_date(monkeypatch) -> None:
    requested = date(2026, 8, 21)

    class DatedRepository(FakeRepository):
        def latest_trade_date(self):
            raise AssertionError("requested trade_date must not fall back to latest")

        def snapshots_by_date(self, trade_date, *, sort_by="entry_score"):
            assert trade_date == requested
            return [{**_snapshot(), "trade_date": requested}]

        def daily_codes_on_date(self, codes, trade_date):
            assert trade_date == requested
            return set(codes)

        def candidates_by_date(self, trade_date, *, limit=5):
            assert trade_date == requested
            return [{**_snapshot(), "trade_date": requested}][:limit]

    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", DatedRepository)
    user = SimpleNamespace(id=1)
    ranking = asyncio.run(etf_rotation.ranking(requested, "entry_score", None, user))
    candidates = asyncio.run(etf_rotation.candidates(requested, 5, user))
    assert ranking["trade_date"] == "2026-08-21"
    assert candidates["trade_date"] == requested


def test_dates_lists_available_snapshot_trade_dates(monkeypatch) -> None:
    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", FakeRepository)
    payload = asyncio.run(etf_rotation.dates(SimpleNamespace(id=1)))
    assert payload["latest"] == "2026-08-25"
    assert payload["items"] == ["2026-08-25", "2026-08-24"]


def test_dates_returns_empty_payload_when_no_snapshots(monkeypatch) -> None:
    class EmptyRepository:
        def available_trade_dates(self):
            return []

    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", EmptyRepository)
    payload = asyncio.run(etf_rotation.dates(SimpleNamespace(id=1)))
    assert payload == {"latest": None, "items": []}


def test_api_is_authenticated_and_fixed_to_cn_market() -> None:
    route_by_path = {route.path: route for route in etf_rotation.router.routes}
    route_paths = [route.path for route in etf_rotation.router.routes]
    assert route_paths.index("/ranking") < route_paths.index("/{code}")
    assert route_paths.index("/candidates") < route_paths.index("/{code}")
    assert route_paths.index("/universe") < route_paths.index("/{code}")
    assert route_paths.index("/dates") < route_paths.index("/{code}")
    for path in ("/ranking", "/candidates", "/universe", "/dates", "/{code}"):
        dependency_calls = {dependency.call for dependency in route_by_path[path].dependant.dependencies}
        assert etf_rotation.require_current_user in dependency_calls
    run_dependencies = {dependency.call for dependency in route_by_path["/run"].dependant.dependencies}
    assert etf_rotation.require_admin in run_dependencies
    assert "market" not in {parameter.name for parameter in route_by_path["/ranking"].dependant.query_params}


def test_scheduler_definition_and_task_registration() -> None:
    definition = require_scheduled_task_definition(JOB_ETF_ROTATION_CN)
    assert definition.celery_task_name == "scheduled.etf_rotation_cn"
    assert definition.schedule_text == "周一至周五 18:40 Asia/Shanghai"
    assert definition.allow_manual_run is True
    assert build_beat_schedule()[JOB_ETF_ROTATION_CN]["options"]["queue"] == "analysis"
    assert "finance_analysis.tasks.celery.jobs.etf_rotation.tasks" in TASK_MODULES


def test_rotation_domain_has_no_redis_quant_feature_or_provider_dependency() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "finance_analysis" / "etf_rotation"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "redis" not in source.lower()
    assert "quant.features" not in source
    assert "providers.akshare" not in source
    assert "providers.efinance" not in source


def test_migration_creates_only_snapshot_table_with_required_constraints() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0027_etf_momentum_snapshot.py"
    ).read_text(encoding="utf-8")
    assert '"etf_momentum_snapshot"' in migration
    assert "uix_etf_momentum_snapshot_date_symbol" in migration
    assert "ix_etf_momentum_snapshot_date_entry" in migration
    assert "ix_etf_momentum_snapshot_symbol_date" in migration
    assert "create_table(\n        \"etf_" not in migration.replace(
        'create_table(\n        "etf_momentum_snapshot"', "expected_snapshot_table"
    )

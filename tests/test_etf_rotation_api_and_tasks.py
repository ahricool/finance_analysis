from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from finance_analysis.interfaces.api.v1.endpoints import etf_rotation
from finance_analysis.interfaces.api.v1.schemas.etf_rotation import ETFRotationRunRequest
from finance_analysis.etf_rotation.universe import enabled_etfs
from finance_analysis.tasks.celery.jobs import TASK_MODULES
from finance_analysis.tasks.celery.schedule import (
    JOB_ETF_ROTATION_CN,
    JOB_ETF_ROTATION_US,
    build_beat_schedule,
    require_scheduled_task_definition,
)


def _snapshot(code="588000.SH"):
    return {
        "id": 1,
        "market": "CN" if code.endswith((".SH", ".SZ")) else "US",
        "trade_date": date(2026, 8, 25),
        "instrument_id": 1,
        "code": code,
        "entry_score": 88.0,
        "momentum_score": 80.0,
        "momentum_strength_score": 80.0,
        "trend_quality_score": 82.0,
        "relative_strength_score": 78.0,
        "acceleration_score": 70.0,
        "efficiency_score": 85.0,
        "composite_score": 79.5,
        "weighted_slope_5d": 0.012,
        "weighted_slope_10d": 0.01,
        "weighted_slope_15d": 0.008,
        "trend_r2_15d": 0.9,
        "signed_efficiency_ratio_10d": 0.8,
        "rs_5d": 0.02,
        "rs_10d": 0.025,
        "rs_20d": 0.03,
        "max_drawdown_20d": -0.05,
        "absolute_trend_eligible": True,
        "liquidity_eligible": True,
        "action": "BUY",
        "reference_price": 100.0,
        "realized_vol_20d": 0.3175,
        "stop_loss_pct": 0.05,
        "suggested_stop_price": 95.0,
        "generated_at": datetime(2026, 8, 25, 10, 40, tzinfo=timezone.utc),
    }


class FakeRepository:
    def __init__(self, market="CN"):
        self.market = market

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

    def exits_by_date(self, trade_date):
        return [{**_snapshot("510300.SH"), "action": "EXIT", "is_candidate": False}]

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
    assert ranking["universe_size"] == len(enabled_etfs("CN"))
    assert candidates["items"][0]["code"] == "588000.SH"
    assert candidates["candidates"][0]["action"] == "BUY"
    assert candidates["exits"][0]["action"] == "EXIT"
    assert detail["metadata"]["theme"] == "STAR50"
    assert detail["latest"]["code"] == "588000.SH"
    for payload in (ranking["items"][0], candidates["items"][0], detail["latest"]):
        assert payload["reference_price"] == 100.0
        assert payload["realized_vol_20d"] == 0.3175
        assert payload["stop_loss_pct"] == 0.05
        assert payload["suggested_stop_price"] == 95.0
        assert payload["composite_score"] == 79.5
        assert payload["weighted_slope_15d"] == 0.008
        assert not ({"user_position", "target_weight", "account", "recommended_exposure"} & payload.keys())


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


def test_candidate_limit_never_hides_exits(monkeypatch) -> None:
    class SplitRepository(FakeRepository):
        def candidates_by_date(self, trade_date, *, limit=5):
            return [
                {**_snapshot(f"51030{index}.SH"), "action": "HOLD", "candidate_rank": index} for index in range(1, 8)
            ][:limit]

        def exits_by_date(self, trade_date):
            return [
                {**_snapshot(f"15990{index}.SZ"), "action": "EXIT", "candidate_rank": None} for index in range(1, 5)
            ]

    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", SplitRepository)
    payload = asyncio.run(etf_rotation.candidates(None, 2, SimpleNamespace(id=1)))
    assert len(payload["candidates"]) == 2
    assert {item["action"] for item in payload["candidates"]} == {"HOLD"}
    assert len(payload["exits"]) == 4
    assert {item["action"] for item in payload["exits"]} == {"EXIT"}
    assert payload["items"] == payload["candidates"]


def test_ranking_builds_daily_changes_from_previous_snapshot(monkeypatch) -> None:
    previous_date = date(2026, 8, 24)

    class ChangesRepository(FakeRepository):
        def previous_trade_date(self, trade_date):
            return previous_date

        def snapshots_by_date(self, trade_date, *, sort_by="composite_score"):
            if trade_date == previous_date:
                return [
                    {
                        **_snapshot(),
                        "trade_date": previous_date,
                        "rank": 12,
                        "state": "STRONG",
                        "action": "HOLD",
                        "composite_score": 72.0,
                    }
                ]
            return [
                {
                    **_snapshot(),
                    "trade_date": trade_date,
                    "rank": 3,
                    "state": "COOLING",
                    "action": "EXIT",
                    "composite_score": 79.5,
                }
            ]

        def market_snapshot_by_date(self, trade_date):
            return {
                "trade_date": trade_date,
                "regime": "RISK_OFF" if trade_date != previous_date else "NEUTRAL",
            }

    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", ChangesRepository)
    payload = asyncio.run(etf_rotation.ranking(None, "composite_score", None, SimpleNamespace(id=1)))
    changes = payload["changes"]
    assert changes["new_exits"][0]["current"]["code"] == "588000.SH"
    assert changes["new_cooling"][0]["previous_state"] == "STRONG"
    assert changes["regime_change"] == {"from": "NEUTRAL", "to": "RISK_OFF"}
    assert changes["rank_movers"][0]["rank_change"] == 9
    assert changes["rank_movers"][0]["composite_score_change"] == 7.5


def test_ranking_serializes_absent_public_action_as_null(monkeypatch) -> None:
    class NullActionRepository(FakeRepository):
        def snapshots_by_date(self, trade_date, *, sort_by="composite_score"):
            return [{**_snapshot(), "action": None, "is_candidate": False, "candidate_rank": None}]

    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", NullActionRepository)
    payload = asyncio.run(etf_rotation.ranking(None, "composite_score", None, SimpleNamespace(id=1)))
    assert payload["items"][0]["action"] is None


def test_dates_lists_available_snapshot_trade_dates(monkeypatch) -> None:
    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", FakeRepository)
    payload = asyncio.run(etf_rotation.dates(SimpleNamespace(id=1)))
    assert payload["market"] == "CN"
    assert payload["latest"] == "2026-08-25"
    assert payload["items"] == ["2026-08-25", "2026-08-24"]


def test_dates_returns_empty_payload_when_no_snapshots(monkeypatch) -> None:
    class EmptyRepository:
        def __init__(self, market="CN"):
            self.market = market

        def available_trade_dates(self):
            return []

    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", EmptyRepository)
    payload = asyncio.run(etf_rotation.dates(SimpleNamespace(id=1)))
    assert payload == {"market": "CN", "latest": None, "items": []}


def test_dates_are_scoped_to_requested_market(monkeypatch) -> None:
    class MarketRepository(FakeRepository):
        def available_trade_dates(self):
            if self.market == "US":
                return [date(2026, 8, 20)]
            return [date(2026, 8, 25), date(2026, 8, 24)]

    monkeypatch.setattr(etf_rotation, "ETFRotationRepository", MarketRepository)
    user = SimpleNamespace(id=1)
    cn = asyncio.run(etf_rotation.dates(user))
    us = asyncio.run(etf_rotation.dates(user, "US"))
    assert cn["market"] == "CN" and cn["items"] == ["2026-08-25", "2026-08-24"]
    assert us["market"] == "US" and us["latest"] == "2026-08-20" and us["items"] == ["2026-08-20"]


def test_api_is_authenticated_and_market_aware_with_cn_default() -> None:
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
    market_parameter = next(
        parameter for parameter in route_by_path["/ranking"].dependant.query_params if parameter.name == "market"
    )
    assert market_parameter.default == "CN"
    dates_market = next(
        parameter for parameter in route_by_path["/dates"].dependant.query_params if parameter.name == "market"
    )
    assert dates_market.default == "CN"


def test_universe_api_separates_cn_and_us_with_cn_default() -> None:
    user = SimpleNamespace(id=1)
    cn = asyncio.run(etf_rotation.universe(user))
    us = asyncio.run(etf_rotation.universe(user, "US"))
    assert cn["market"] == "CN" and cn["size"] == len(enabled_etfs("CN"))
    assert us["market"] == "US" and us["size"] == 49
    assert {"SPY.US", "QQQ.US", "IWM.US"} <= {item["code"] for item in us["items"]}


def test_scheduler_definition_and_task_registration() -> None:
    definition = require_scheduled_task_definition(JOB_ETF_ROTATION_CN)
    assert definition.celery_task_name == "scheduled.etf_rotation_cn"
    assert definition.schedule_text == "周一至周五 18:30 Asia/Shanghai"
    assert definition.allow_manual_run is True
    assert build_beat_schedule()[JOB_ETF_ROTATION_CN]["options"]["queue"] == "analysis"
    us_definition = require_scheduled_task_definition(JOB_ETF_ROTATION_US)
    assert us_definition.celery_task_name == "scheduled.etf_rotation_us"
    assert us_definition.schedule_text == "周一至周五 18:30 America/New_York"
    assert build_beat_schedule()[JOB_ETF_ROTATION_US]["options"]["queue"] == "analysis"
    assert "finance_analysis.tasks.celery.jobs.etf_rotation.tasks" in TASK_MODULES


def test_manual_us_run_submits_the_us_task(monkeypatch) -> None:
    from finance_analysis.tasks.celery.jobs.etf_rotation import tasks

    cn_submit = MagicMock()
    us_submit = MagicMock(return_value=SimpleNamespace(id="us-task-id"))
    monkeypatch.setattr(tasks.run_etf_rotation_cn, "apply_async", cn_submit)
    monkeypatch.setattr(tasks.run_etf_rotation_us, "apply_async", us_submit)

    response = asyncio.run(etf_rotation.run_rotation(ETFRotationRunRequest(market="US"), SimpleNamespace(id=7)))

    assert response["market"] == "US"
    assert response["task_id"] == "us-task-id"
    cn_submit.assert_not_called()
    assert us_submit.call_args.kwargs["queue"] == "analysis"


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
    assert 'create_table(\n        "etf_' not in migration.replace(
        'create_table(\n        "etf_momentum_snapshot"', "expected_snapshot_table"
    )

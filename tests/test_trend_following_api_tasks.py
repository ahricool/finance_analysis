from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from finance_analysis.core.paths import PROJECT_ROOT  # pragma: allowlist secret
from finance_analysis.interfaces.api.v1.endpoints import trend_following  # pragma: allowlist secret
from finance_analysis.interfaces.api.v1.schemas.trend_following import TrendFollowingRunRequest  # pragma: allowlist secret
from finance_analysis.tasks.celery.jobs import TASK_MODULES  # pragma: allowlist secret
from finance_analysis.tasks.celery.schedule import (  # pragma: allowlist secret
    JOB_TREND_FOLLOWING_CN,
    JOB_TREND_FOLLOWING_US,
    build_beat_schedule,
    require_scheduled_task_definition,
)

TRADE_DATE = date(2026, 8, 28)


class FakeRepository:
    def __init__(self, market):
        self.market = market

    def historical_composite_ranks(self, trade_date, codes):
        return {}

    def latest_trade_date(self):
        return date(2026, 8, 29)

    def available_trade_dates(self):
        return [date(2026, 8, 29), TRADE_DATE]

    def summary_by_date(self, trade_date):
        return {
            "market": self.market,
            "trade_date": trade_date,
            "market_regime": "RISK_ON",
            "market_score": 80,
            "data_coverage": 1,
        }

    def snapshots_by_date(self, trade_date, *, sort_by, limit):
        return [{"code": "AAPL.US", "trade_date": trade_date, "alpha_score": 80, "rank": 1}]

    def dashboard_rows(self, trade_date):
        return self.snapshots_by_date(trade_date, sort_by="rank", limit=None)

    def change_rows(self, trade_date):
        return self.snapshots_by_date(trade_date, sort_by="rank", limit=None)

    def candidates_by_date(self, trade_date, *, limit):
        return [{"code": "AAPL.US", "trade_date": trade_date, "state": "CANDIDATE"}]

    def snapshot_rows(self, trade_date):
        return [
            {
                "code": "AAPL.US",
                "name": "Apple",
                "trade_date": trade_date,
                "state": "TRENDING",
                "reference_price": 195.0,
                "alpha_score": 82.5,
            }
        ]

    def snapshot_history(self, code, *, limit, as_of=None, before_trade_date=None):
        rows = [
            {"code": code, "name": "Apple", "trade_date": date(2026, 8, 29), "state": "TRENDING"},
            {"code": code, "name": "Apple", "trade_date": TRADE_DATE, "state": "CANDIDATE"},
        ]
        if as_of is not None:
            rows = [row for row in rows if row["trade_date"] <= as_of]
        if before_trade_date is not None:
            rows = [row for row in rows if row["trade_date"] < before_trade_date]
        return rows


def test_snapshot_api_contracts(monkeypatch):
    monkeypatch.setattr(trend_following, "TrendFollowingRepository", FakeRepository)
    monkeypatch.setattr(
        trend_following,
        "universe_by_code",
        lambda market: {
            "AAPL.US": SimpleNamespace(
                code="AAPL.US", name="Apple", to_dict=lambda: {"code": "AAPL.US", "name": "Apple"}
            )
        },
    )
    user = SimpleNamespace(id=1)
    ranking = json.loads(trend_following.ranking(None, "alpha_score", None, user, "US").body)
    candidates = trend_following.candidates(None, 100, user, "US")
    dates = trend_following.dates(user, "US")
    detail = trend_following.detail("AAPL.US", 60, TRADE_DATE, user, "US")
    assert ranking["items"][0]["code"] == "AAPL.US"
    assert candidates["items"][0]["state"] == "CANDIDATE"
    assert dates["latest"] == "2026-08-29"
    assert detail["latest"]["state"] == "CANDIDATE"
    assert detail["latest"]["trade_date"] == "2026-08-28"
    assert all(item["trade_date"] <= "2026-08-28" for item in detail["history"])
    latest = trend_following.detail("AAPL.US", 60, None, user, "US")
    assert latest["latest"]["trade_date"] == "2026-08-29"
    history = trend_following.detail("AAPL.US", 60, None, user, "US", before_trade_date=date(2026, 8, 29))
    assert set(history) == {"history"}
    assert [row["trade_date"] for row in history["history"]] == ["2026-08-28"]
    assert trend_following.detail("AAPL.US", 60, None, user, "US", before_trade_date=TRADE_DATE) == {"history": []}
    with pytest.raises(HTTPException) as error:
        trend_following.detail("AAPL.US", 60, TRADE_DATE, user, "US", before_trade_date=TRADE_DATE)
    assert error.value.status_code == 422





def test_ranking_reuses_previous_snapshots_for_daily_changes(monkeypatch):
    previous_date = date(2026, 8, 27)

    class ChangesRepository(FakeRepository):
        def previous_trade_date(self, trade_date):
            assert trade_date == TRADE_DATE
            return previous_date

        def summary_by_date(self, trade_date):
            return {
                "market": self.market,
                "trade_date": trade_date,
                "market_regime": "RISK_ON",
                "market_score": 75 if trade_date == TRADE_DATE else 70,
                "score_breakdown": {"breadth": 65 if trade_date == TRADE_DATE else 60},
            }

        def snapshots_by_date(self, trade_date, *, sort_by, limit):
            assert sort_by in {"alpha_score", "rank"}
            if trade_date == previous_date:
                return [
                    {
                        "code": "AAPL.US",
                        "trade_date": trade_date,
                        "rank": 12,
                        "state": "WATCHING",
                        "trend_score": 60,
                        "rs_score": 58,
                        "alpha_score": 62,
                    }
                ]
            return [
                {
                    "code": "AAPL.US",
                    "trade_date": trade_date,
                    "rank": 3,
                    "state": "CANDIDATE",
                    "trend_score": 69,
                    "rs_score": 66,
                    "alpha_score": 70,
                }
            ]

    monkeypatch.setattr(trend_following, "TrendFollowingRepository", ChangesRepository)
    payload = json.loads(trend_following.ranking(TRADE_DATE, "alpha_score", None, SimpleNamespace(id=1), "US").body)
    changes = payload["changes"]
    assert changes["market_score_change"] == 5
    assert changes["breadth_score_change"] == 5
    assert changes["new_candidates"][0]["code"] == "AAPL.US"
    assert changes["transitions"][0]["previous_state"] == "WATCHING"
    assert changes["movers"][0]["rank_change"] == 9


def test_historical_detail_requires_an_exact_snapshot_date(monkeypatch):
    monkeypatch.setattr(trend_following, "universe_by_code", lambda market: {"AAPL.US": {}})
    monkeypatch.setattr(trend_following, "TrendFollowingRepository", FakeRepository)
    with pytest.raises(HTTPException) as error:
        trend_following.detail(
                "AAPL.US",
                60,
                date(2026, 8, 27),
                SimpleNamespace(id=1),
                "US",
            )
    assert error.value.status_code == 404


def test_tasks_and_schedules_are_registered():
    cn = require_scheduled_task_definition(JOB_TREND_FOLLOWING_CN)
    us = require_scheduled_task_definition(JOB_TREND_FOLLOWING_US)
    assert cn.celery_task_name == "scheduled.trend_following_cn"
    assert us.celery_task_name == "scheduled.trend_following_us"
    assert cn.schedule_text.startswith("周一至周五 18:40")
    assert us.schedule_text.startswith("周一至周五 18:40")
    assert build_beat_schedule()[JOB_TREND_FOLLOWING_CN]["options"]["queue"] == "analysis"
    assert build_beat_schedule()[JOB_TREND_FOLLOWING_US]["options"]["queue"] == "analysis"
    assert "finance_analysis.tasks.celery.jobs.trend_following.tasks" in TASK_MODULES  # pragma: allowlist secret
    preview_cn = require_scheduled_task_definition("trend_following_preview_cn")
    preview_us = require_scheduled_task_definition("trend_following_preview_us")
    assert preview_cn.celery_task_name == "scheduled.trend_following_preview_cn"
    assert preview_us.celery_task_name == "scheduled.trend_following_preview_us"
    assert {(item.hour, item.minute) for item in preview_cn.schedules} == {("11", "0"), ("14", "0"), ("14", "30")}
    assert {(item.hour, item.minute, item.timezone) for item in preview_us.schedules} == {
        ("11", "0", "America/New_York"),
        ("15", "0", "America/New_York"),
        ("15", "30", "America/New_York"),
    }


def test_manual_run_submits_celery(monkeypatch):
    submitted = {}
    fake_result = SimpleNamespace(id="trend-task")

    def submit(**kwargs):
        submitted.update(kwargs)
        return fake_result

    from finance_analysis.tasks.celery.jobs.trend_following import tasks  # pragma: allowlist secret

    monkeypatch.setattr(tasks.run_trend_following_us, "apply_async", submit)
    result = trend_following.run_trend_following(
            TrendFollowingRunRequest(market="US", trade_date=TRADE_DATE), SimpleNamespace(id=7)
        )
    assert result["task_id"] == "trend-task"
    assert submitted["kwargs"]["trade_date"] == "2026-08-28"
    assert submitted["queue"] == "analysis"
    submitted.clear()
    latest = trend_following.run_trend_following(
            TrendFollowingRunRequest(market="US", trade_date=None), SimpleNamespace(id=7)
        )
    assert latest["task_id"] == "trend-task"
    assert submitted["kwargs"]["trade_date"] is None


def test_migration_and_snapshot_have_no_user_columns():
    import importlib.util

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from finance_analysis.database.models.trend_following import TrendFollowingSnapshot, TrendFollowingSummary
    from finance_analysis.trend_following.state import transition_state

    path = Path(PROJECT_ROOT) / "alembic/versions/0053_trend_states.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    metadata = sa.MetaData()
    snapshot = sa.Table(
        "trend_following_snapshot", metadata,
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("market", sa.String),
        sa.Column("code", sa.String), sa.Column("trade_date", sa.Date), sa.Column("state", sa.String),
        sa.Column("reference_price", sa.Float), sa.Column("trend_score", sa.Float),
        sa.Column("rs_score", sa.Float), sa.Column("alpha_score", sa.Float),
        sa.Column("features", sa.JSON), sa.Column("reasons", sa.JSON),
        *(sa.Column(key, sa.Float) for key in migration.SNAPSHOT_COLUMNS),
        sa.CheckConstraint("units BETWEEN 0 AND 4", name="ck_trend_following_units"),
    )
    summary = sa.Table(
        "trend_following_summary", metadata,
        sa.Column("market", sa.String), sa.Column("trade_date", sa.Date), sa.Column("candidate_count", sa.Integer),
        *(sa.Column(key, sa.Float) for key in migration.SUMMARY_COLUMNS),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    features = {"ma10": 108, "ma20": 104, "ma20_slope": 0.01, "previous_low_10": 100,
                "trend_candidate": True, "valid_setup": True}
    days = [date(2026, 9, day) for day in (7, 8, 9)]
    with engine.begin() as connection:
        for index, (day, price) in enumerate(zip(days, (110, 111, 99)), 1):
            connection.execute(snapshot.insert(), {"id": index, "market": "US", "code": "AAA.US",
                "trade_date": day, "state": "HOLDING", "reference_price": price, "trend_score": 80,
                "rs_score": 80, "alpha_score": 80, "features": features, "reasons": ["old execution context"]})
            connection.execute(summary.insert(), {"market": "US", "trade_date": day, "candidate_count": 0})
        connection.execute(snapshot.insert(), {"id": 4, "market": "US", "code": "BBB.US",
            "trade_date": days[-1], "state": "HOLDING", "reference_price": 110, "trend_score": 80,
            "rs_score": 80, "alpha_score": 80, "features": features,
            "reasons": ["current daily data unavailable; active state carried forward"]})
        operations = Operations(MigrationContext.configure(connection))

        class SQLiteOperations:
            get_bind = staticmethod(lambda: connection)
            execute = staticmethod(operations.execute)

            def drop_constraint(self, name, table, **kwargs):
                with operations.batch_alter_table(table) as batch:
                    batch.drop_constraint(name, **kwargs)

            def drop_column(self, table, column):
                with operations.batch_alter_table(table) as batch:
                    batch.drop_column(column)

            def create_check_constraint(self, name, table, condition):
                with operations.batch_alter_table(table) as batch:
                    batch.create_check_constraint(name, condition)

        migration.op = SQLiteOperations()
        migration.upgrade()
        actual = connection.execute(sa.text("SELECT state FROM trend_following_snapshot ORDER BY trade_date")).scalars().all()
        expected, previous = [], None
        for price in (110, 111, 99):
            previous = transition_state({**features, "reference_price": price, "trend_score": 80,
                                         "rs_score": 80, "is_candidate": True}, previous).to_dict()
            expected.append(previous["state"])
        assert actual == expected == ["CANDIDATE", "TRENDING", "BROKEN"]
        assert connection.execute(sa.select(summary.c.candidate_count).order_by(summary.c.trade_date)).scalars().all() == [1, 0, 0]
        for table, removed, model in (
            ("trend_following_snapshot", migration.SNAPSHOT_COLUMNS, TrendFollowingSnapshot),
            ("trend_following_summary", migration.SUMMARY_COLUMNS, TrendFollowingSummary),
        ):
            columns = {column["name"] for column in sa.inspect(connection).get_columns(table)}
            assert not set(removed) & columns
            assert not set(removed) & set(model.__table__.c.keys())
        assert not {"uid", "user_id", "account_id", "position_id"} & set(TrendFollowingSnapshot.__table__.c.keys())
        assert "old execution context" not in str(connection.execute(sa.text("SELECT reasons FROM trend_following_snapshot")).all())


def test_ranking_includes_rank_changes_for_limited_items(monkeypatch):
    class HistoryRepository(FakeRepository):
        def historical_composite_ranks(self, trade_date, codes):
            assert trade_date == TRADE_DATE
            assert codes == ["AAPL.US"]
            return {"AAPL.US": {1: 6, 3: 18, 5: 33}}

    monkeypatch.setattr(trend_following, "TrendFollowingRepository", HistoryRepository)
    result = json.loads(trend_following.ranking(TRADE_DATE, "rank", 1, SimpleNamespace(id=1), "US").body)
    assert {key: value for key, value in result["items"][0].items() if key.startswith("rank_change")} == {
        "rank_change_1d": 5, "rank_change_3d": 17, "rank_change_5d": 32,
    }


@pytest.mark.parametrize("market", ["CN", "US"])
@pytest.mark.parametrize("status", ["completed", "failed", "incomplete"])
def test_trend_task_business_status_drives_existing_lifecycle(monkeypatch, market, status):
    from contextlib import nullcontext
    from unittest.mock import Mock
    from finance_analysis.tasks import lifecycle
    from finance_analysis.tasks.celery.jobs.trend_following import tasks  # pragma: allowlist secret

    result = {
        "status": status,
        "market": market,
        "trade_date": "2026-09-08",
        "warnings": ["daily data coverage below 90%"],
        "data_coverage": 475 / 503,
    }
    service = Mock()
    notification = Mock()
    domain = Mock()
    domain.run.return_value = result
    monkeypatch.setattr(tasks, "TrendFollowingService", lambda actual_market: domain)
    monkeypatch.setattr(lifecycle, "get_task_lifecycle_service", lambda: service)
    monkeypatch.setattr(lifecycle, "task_logging_context", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(lifecycle, "_relative_task_log_path", lambda *args, **kwargs: "fake.log")
    monkeypatch.setattr(lifecycle, "_send_task_failure_notification", notification)
    task = tasks.run_trend_following_cn if market == "CN" else tasks.run_trend_following_us
    if status == "completed":
        assert task.run(trade_date="2026-09-08") == result
        service.mark_completed.assert_called_once()
        service.mark_failed.assert_not_called()
        notification.assert_not_called()
    else:
        with pytest.raises(RuntimeError) as error:
            task.run(trade_date="2026-09-08")
        for detail in (market, "2026-09-08", status, "warnings", "data_coverage"):
            assert detail in str(error.value)
        service.mark_failed.assert_called_once()
        service.mark_completed.assert_not_called()
        notification.assert_called_once()
    domain.run.assert_called_once_with(date(2026, 9, 8))


@pytest.fixture(autouse=True)
def offline_ranking_cache(monkeypatch):
    monkeypatch.setattr(trend_following.RankingCache, "load", lambda self: None)
    monkeypatch.setattr(trend_following.RankingCache, "save", lambda self, body: None)


def test_ranking_cache_hit_only_resolves_latest_date(monkeypatch):
    calls = []

    class CachedRepository(FakeRepository):
        def latest_trade_date(self):
            calls.append("latest")
            return TRADE_DATE

        def dashboard_rows(self, trade_date):
            pytest.fail("cache hit queried snapshots")

    monkeypatch.setattr(trend_following, "TrendFollowingRepository", CachedRepository)
    monkeypatch.setattr(trend_following.RankingCache, "load", lambda self: b'{"cached":true}')
    assert json.loads(trend_following.ranking(None, "alpha_score", None, None, "CN").body) == {"cached": True}
    assert calls == ["latest"]
    calls.clear()
    trend_following.ranking(TRADE_DATE, "alpha_score", None, None, "CN")
    assert calls == []


def test_changes_classification_uses_lightweight_fields():
    previous = [{"code": code, "state": "WATCHING", "rank": 9}
                for code in ("A", "B", "C", "D")]
    current = [
        {"code": "A", "state": "CANDIDATE", "rank": 1},
        {"code": "B", "state": "WEAKENING", "rank": 2},
        {"code": "C", "state": "TRENDING", "rank": 3},
        {"code": "D", "state": "BROKEN", "rank": 4},
    ]
    repo = SimpleNamespace(previous_trade_date=lambda day: TRADE_DATE,
                           change_rows=lambda day: previous,
                           summary_by_date=lambda day: {"market_score": 70})
    result = trend_following._changes(repo, TRADE_DATE, current, {"market_score": 75})
    for category, code in [("new_candidates", "A"), ("new_weakening", "B"), ("new_broken", "D")]:
        assert [item["code"] for item in result[category]] == [code]
    assert len(result["transitions"]) == 4
    assert all("current" not in item for key, value in result.items() if isinstance(value, list) for item in value)


def test_ranking_aggregates_without_compatibility_queries_and_does_not_cache_incomplete(monkeypatch):
    saves = []

    class ProjectionRepository(FakeRepository):
        def dashboard_rows(self, trade_date):
            assert trade_date == TRADE_DATE
            return [{**self.snapshot_rows(trade_date)[0], "rank": 1}]

        def candidates_by_date(self, *args, **kwargs):
            pytest.fail("ranking must reuse projection")

        def summary_by_date(self, trade_date):
            return {**super().summary_by_date(trade_date), "data_coverage": 0.5}

    monkeypatch.setattr(trend_following, "TrendFollowingRepository", ProjectionRepository)
    monkeypatch.setattr(trend_following.RankingCache, "save", lambda self, body: saves.append(body))
    result = json.loads(trend_following.ranking(TRADE_DATE, "alpha_score", None, None, "US").body)
    assert "portfolio" not in result
    assert result["candidates"][0]["code"] == result["items"][0]["code"]
    assert "score_breakdown" not in result["items"][0]
    assert "reasons" not in result["items"][0]
    assert saves == []


def test_historical_heatmap_detail_can_open_a_former_universe_member(monkeypatch):
    monkeypatch.setattr(trend_following, "universe_by_code", lambda market: {})
    monkeypatch.setattr(trend_following, "TrendFollowingRepository", FakeRepository)
    result = trend_following.detail("AAPL.US", 60, TRADE_DATE, SimpleNamespace(id=1), "US")
    assert result["metadata"] == {"market": "US", "code": "AAPL.US", "name": "Apple"}
    assert result["latest"]["trade_date"] == TRADE_DATE.isoformat()
    with pytest.raises(HTTPException) as error:
        trend_following.detail("AAPL.US", 60, date(2026, 1, 1), SimpleNamespace(id=1), "US")
    assert error.value.status_code == 404

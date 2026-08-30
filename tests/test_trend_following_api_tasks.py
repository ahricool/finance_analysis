from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from finance_analysis.core.paths import PROJECT_ROOT
from finance_analysis.interfaces.api.v1.endpoints import trend_following
from finance_analysis.interfaces.api.v1.schemas.trend_following import TrendFollowingRunRequest
from finance_analysis.tasks.celery.jobs import TASK_MODULES
from finance_analysis.tasks.celery.schedule import (
    JOB_TREND_FOLLOWING_CN,
    JOB_TREND_FOLLOWING_US,
    build_beat_schedule,
    require_scheduled_task_definition,
)

TRADE_DATE = date(2026, 8, 28)


class FakeRepository:
    def __init__(self, market): self.market = market
    def latest_trade_date(self): return TRADE_DATE
    def available_trade_dates(self): return [TRADE_DATE]
    def summary_by_date(self, trade_date):
        return {"market": self.market, "trade_date": trade_date, "market_regime": "RISK_ON", "market_score": 80}
    def snapshots_by_date(self, trade_date, *, sort_by, limit):
        return [{"code": "AAPL.US", "trade_date": trade_date, "alpha_score": 80}]
    def candidates_by_date(self, trade_date, *, limit):
        return [{"code": "AAPL.US", "trade_date": trade_date, "state": "ENTRY"}]
    def snapshot_history(self, code, *, limit):
        return [{"code": code, "name": "Apple", "trade_date": TRADE_DATE, "state": "ENTRY"}]


def test_snapshot_api_contracts(monkeypatch):
    monkeypatch.setattr(trend_following, "TrendFollowingRepository", FakeRepository)
    user = SimpleNamespace(id=1)
    ranking = asyncio.run(trend_following.ranking(None, "alpha_score", None, user, "US"))
    candidates = asyncio.run(trend_following.candidates(None, 100, user, "US"))
    dates = asyncio.run(trend_following.dates(user, "US"))
    detail = asyncio.run(trend_following.detail("AAPL.US", 60, user, "US"))
    assert ranking["items"][0]["code"] == "AAPL.US"
    assert candidates["items"][0]["state"] == "ENTRY"
    assert dates["latest"] == "2026-08-28"
    assert detail["latest"]["state"] == "ENTRY"


def test_tasks_and_schedules_are_registered():
    cn = require_scheduled_task_definition(JOB_TREND_FOLLOWING_CN)
    us = require_scheduled_task_definition(JOB_TREND_FOLLOWING_US)
    assert cn.celery_task_name == "scheduled.trend_following_cn"
    assert us.celery_task_name == "scheduled.trend_following_us"
    assert cn.schedule_text.startswith("周一至周五 19:30")
    assert us.schedule_text.startswith("周一至周五 22:00")
    assert build_beat_schedule()[JOB_TREND_FOLLOWING_CN]["options"]["queue"] == "analysis"
    assert build_beat_schedule()[JOB_TREND_FOLLOWING_US]["options"]["queue"] == "analysis"
    assert "finance_analysis.tasks.celery.jobs.trend_following.tasks" in TASK_MODULES


def test_manual_run_submits_celery(monkeypatch):
    submitted = {}
    fake_result = SimpleNamespace(id="trend-task")

    def submit(**kwargs):
        submitted.update(kwargs)
        return fake_result

    from finance_analysis.tasks.celery.jobs.trend_following import tasks
    monkeypatch.setattr(tasks.run_trend_following_us, "apply_async", submit)
    result = asyncio.run(trend_following.run_trend_following(
        TrendFollowingRunRequest(market="US", trade_date=TRADE_DATE), SimpleNamespace(id=7)
    ))
    assert result["task_id"] == "trend-task"
    assert submitted["kwargs"]["trade_date"] == "2026-08-28"
    assert submitted["queue"] == "analysis"


def test_migration_and_snapshot_have_no_user_columns():
    migration = (Path(PROJECT_ROOT) / "alembic/versions/0031_trend_following.py").read_text(encoding="utf-8")
    assert 'revision: str = "0031_trend_following"' in migration
    assert 'down_revision: Union[str, Sequence[str], None] = "0030_etf_rotation_v2"' in migration
    for column in ("uid", "user_id", "account_id", "position_id", "user_cost", "user_weight", "user_pnl"):
        assert f'Column("{column}"' not in migration

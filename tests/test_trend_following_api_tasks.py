from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
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
    def latest_trade_date(self): return date(2026, 8, 29)
    def available_trade_dates(self): return [date(2026, 8, 29), TRADE_DATE]
    def summary_by_date(self, trade_date):
        return {"market": self.market, "trade_date": trade_date, "market_regime": "RISK_ON", "market_score": 80}
    def snapshots_by_date(self, trade_date, *, sort_by, limit):
        return [{"code": "AAPL.US", "trade_date": trade_date, "alpha_score": 80}]
    def candidates_by_date(self, trade_date, *, limit):
        return [{"code": "AAPL.US", "trade_date": trade_date, "state": "ENTRY"}]
    def snapshot_history(self, code, *, limit, as_of=None):
        rows = [
            {"code": code, "name": "Apple", "trade_date": date(2026, 8, 29), "state": "HOLDING"},
            {"code": code, "name": "Apple", "trade_date": TRADE_DATE, "state": "ENTRY"},
        ]
        if as_of is not None:
            rows = [row for row in rows if row["trade_date"] <= as_of]
        return rows


def test_snapshot_api_contracts(monkeypatch):
    monkeypatch.setattr(trend_following, "TrendFollowingRepository", FakeRepository)
    user = SimpleNamespace(id=1)
    ranking = asyncio.run(trend_following.ranking(None, "alpha_score", None, user, "US"))
    candidates = asyncio.run(trend_following.candidates(None, 100, user, "US"))
    dates = asyncio.run(trend_following.dates(user, "US"))
    detail = asyncio.run(trend_following.detail("AAPL.US", 60, TRADE_DATE, user, "US"))
    assert ranking["items"][0]["code"] == "AAPL.US"
    assert candidates["items"][0]["state"] == "ENTRY"
    assert dates["latest"] == "2026-08-29"
    assert detail["latest"]["state"] == "ENTRY"
    assert detail["latest"]["trade_date"] == "2026-08-28"
    assert all(item["trade_date"] <= "2026-08-28" for item in detail["history"])
    latest = asyncio.run(trend_following.detail("AAPL.US", 60, None, user, "US"))
    assert latest["latest"]["trade_date"] == "2026-08-29"


def test_historical_detail_requires_an_exact_snapshot_date(monkeypatch):
    monkeypatch.setattr(trend_following, "TrendFollowingRepository", FakeRepository)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            trend_following.detail(
                "AAPL.US", 60, date(2026, 8, 27), SimpleNamespace(id=1), "US",
            )
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
    submitted.clear()
    latest = asyncio.run(trend_following.run_trend_following(
        TrendFollowingRunRequest(market="US", trade_date=None), SimpleNamespace(id=7)
    ))
    assert latest["task_id"] == "trend-task"
    assert submitted["kwargs"]["trade_date"] is None


def test_migration_and_snapshot_have_no_user_columns():
    migration = (Path(PROJECT_ROOT) / "alembic/versions/0031_trend_following.py").read_text(encoding="utf-8")
    assert 'revision: str = "0031_trend_following"' in migration
    assert 'down_revision: Union[str, Sequence[str], None] = "0030_etf_rotation_v2"' in migration
    for column in ("uid", "user_id", "account_id", "position_id", "user_cost", "user_weight", "user_pnl"):
        assert f'Column("{column}"' not in migration
    signal = (Path(PROJECT_ROOT) / "alembic/versions/0032_trend_following_signal.py").read_text(encoding="utf-8")
    assert 'revision: str = "0032_trend_following_signal"' in signal
    assert 'down_revision: Union[str, Sequence[str], None] = "0031_trend_following"' in signal
    assert "signal_date" in signal
    assert "signal_price" in signal
    assert "0031_trend_following" in migration
    pending = (
        Path(PROJECT_ROOT) / "alembic/versions/0033_trend_following_pending_action.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0033_trend_pending_action"' in pending
    assert 'down_revision: Union[str, Sequence[str], None] = "0032_trend_following_signal"' in pending
    assert "pending_action" in pending
    assert "pending_since" in pending
    execution = (
        Path(PROJECT_ROOT) / "alembic/versions/0034_trend_following_execution_context.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0034_trend_execution_context"' in execution
    assert 'down_revision: Union[str, Sequence[str], None] = "0033_trend_pending_action"' in execution
    assert "pending_regime" in execution
    assert "pending_max_exposure" in execution

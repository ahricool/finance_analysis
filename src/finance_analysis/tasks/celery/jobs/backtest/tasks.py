"""Celery entrypoint for one persisted backtest run."""

from __future__ import annotations

from finance_analysis.backtest.service import BacktestService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name="backtest.run")
@track_task(
    task_type="backtest",
    task_name="策略回测",
    source="celery_manual",
    uid_getter=lambda backtest_run_id, owner_uid=None, **_: owner_uid,
    record_result=True,
    success_message="策略回测完成",
)
def run_backtest(backtest_run_id: int, owner_uid: int | None = None) -> dict:
    del owner_uid
    return BacktestService().execute_run(backtest_run_id)


__all__ = ["run_backtest"]

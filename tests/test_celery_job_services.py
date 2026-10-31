"""Tests for business services behind periodic Celery task entry points."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from finance_analysis.tasks.celery.jobs.market_calendar_sync import service as calendar_module
from finance_analysis.tasks.celery.jobs.scheduled_support import (
    INTRADAY_START_DELAY_MAX_SECONDS,
    sleep_random_start_delay,
)


def test_intraday_start_delay_is_bounded():
    with (
        patch("finance_analysis.tasks.celery.jobs.scheduled_support.random.uniform", return_value=3.25) as uniform,
        patch("finance_analysis.tasks.celery.jobs.scheduled_support.time.sleep") as sleep,
    ):
        delay = sleep_random_start_delay(task_name="盘中测试任务")

    uniform.assert_called_once_with(0.0, INTRADAY_START_DELAY_MAX_SECONDS)
    sleep.assert_called_once_with(3.25)
    assert delay == 3.25


def test_market_calendar_service_runs_sync_and_submits_importance():
    summary = MagicMock(
        all_interfaces_failed=False,
        all_writes_failed=False,
        fetched_count_by_type={"earnings": 1},
        inserted_count=1,
        updated_count=0,
        skipped_duplicate_count=0,
        notification_created_count=1,
        importance_candidate_ids=[11, 12],
    )
    summary.to_dict.return_value = {"importance_candidate_ids": [11, 12]}
    domain_service = MagicMock()
    domain_service.run.return_value = summary
    task_service = calendar_module.MarketCalendarSyncTaskService()
    with (
        patch(
            "finance_analysis.tasks.celery.jobs.market_calendar_sync.domain_service.MarketCalendarSyncService",
            return_value=domain_service,
        ),
        patch.object(task_service, "_submit_importance_task") as submit,
    ):
        result = task_service.run()

    submit.assert_called_once_with([11, 12])
    assert result["importance_candidate_ids"] == [11, 12]


def test_market_calendar_importance_submission_failure_is_non_fatal():
    with patch(
        "finance_analysis.tasks.celery.jobs.market_calendar_importance.tasks." "market_calendar_importance.apply_async",
        side_effect=RuntimeError("broker down"),
    ) as submit:
        calendar_module.MarketCalendarSyncTaskService._submit_importance_task([1, 2])

    submit.assert_called_once()

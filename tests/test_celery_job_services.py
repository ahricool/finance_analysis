"""Tests for business services behind periodic Celery task entry points."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from finance_analysis.tasks.celery.jobs.market_calendar_sync import service as calendar_module
from finance_analysis.tasks.celery.jobs.us_postmarket_review import service as postmarket_module
from finance_analysis.tasks.celery.jobs.us_premarket_news import service as premarket_news_module
from finance_analysis.tasks.celery.jobs.scheduled_support import (
    INTRADAY_START_DELAY_MAX_SECONDS,
    sleep_random_start_delay,
)


def test_us_premarket_news_service_runs_domain_service():
    summary = MagicMock(symbols_count=22)
    domain_service = MagicMock()
    domain_service.run.return_value = summary
    with (
        patch("finance_analysis.market_review.runtime_config.get_market_review_runtime_config", return_value=MagicMock()) as config,
        patch(
            "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market",
            return_value=["AAPL", "TSLA"],
        ),
        patch(
            "finance_analysis.tasks.celery.jobs.us_premarket_news.domain_service.USPremarketNewsService",
            return_value=domain_service,
        ) as service_class,
    ):
        premarket_news_module.USPremarketNewsTaskService().run()

    service_class.assert_called_once_with(config=config.return_value)
    assert domain_service.run.call_args.args[0] == ["AAPL", "TSLA"]


def test_premarket_news_retains_watch_validation_failure_after_report_success():
    from finance_analysis.database.repositories.watch_list import WatchListCodes
    from finance_analysis.tasks.outcomes import report_delivery_outcome

    invalid = {"watch_list_id": 7, "code": "600519.SH", "market_type": "US", "error": "market conflict"}
    codes = WatchListCodes(["MSFT.US"], validation_failures=[invalid])
    summary = MagicMock(symbols_count=22, channel_results={"telegram": True, "ntfy": True})
    domain_service = MagicMock()
    domain_service.run.return_value = summary
    with (
        patch("finance_analysis.market_review.runtime_config.get_market_review_runtime_config", return_value=MagicMock()),
        patch("finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market", return_value=codes),
        patch("finance_analysis.tasks.celery.jobs.us_premarket_news.domain_service.USPremarketNewsService",
              return_value=domain_service),
    ):
        result = premarket_news_module.USPremarketNewsTaskService().run()

    assert domain_service.run.call_args.args[0] == ["MSFT.US"]
    assert result["validation_failures"] == [invalid]
    assert report_delivery_outcome(result).status.value == "partial"


def test_us_postmarket_service_returns_domain_summary():
    domain_service = MagicMock()
    domain_service.run.return_value.to_dict.return_value = {"market_regime": "risk_on"}
    with (
        patch("finance_analysis.market_review.runtime_config.get_market_review_runtime_config", return_value=MagicMock()) as config,
        patch(
            "finance_analysis.tasks.celery.jobs.us_postmarket_review.domain_service.USPostmarketReviewService",
            return_value=domain_service,
        ) as service_class,
    ):
        result = postmarket_module.USPostmarketReviewTaskService().run()

    service_class.assert_called_once_with(config=config.return_value)
    domain_service.run.assert_called_once_with(send_notification=True)
    assert result["market_regime"] == "risk_on"


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
        "finance_analysis.tasks.celery.jobs.market_calendar_importance.tasks."
        "market_calendar_importance.apply_async",
        side_effect=RuntimeError("broker down"),
    ) as submit:
        calendar_module.MarketCalendarSyncTaskService._submit_importance_task([1, 2])

    submit.assert_called_once()

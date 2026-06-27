"""Tests for business services behind periodic Celery task entry points."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis import service as a_share_module
from finance_analysis.tasks.celery.jobs.daily_analysis import service as daily_module
from finance_analysis.tasks.celery.jobs.market_calendar_sync import service as calendar_module
from finance_analysis.tasks.celery.jobs.us_intraday_analysis import service as us_intraday_module
from finance_analysis.tasks.celery.jobs.us_postmarket_review import service as postmarket_module
from finance_analysis.tasks.celery.jobs.us_premarket_analysis import service as premarket_module
from finance_analysis.tasks.celery.jobs.us_premarket_news import service as premarket_news_module
from finance_analysis.tasks.celery.jobs.scheduled_support import (
    INTRADAY_START_DELAY_MAX_SECONDS,
    sleep_random_start_delay,
)
from finance_analysis.tasks.lifecycle import TaskSkipped


def test_daily_task_service_invokes_pipeline_and_records_result():
    pipeline = MagicMock()
    pipeline.run.return_value = []
    with (
        patch("finance_analysis.analysis.pipeline_config.get_pipeline_config", return_value=MagicMock()) as config,
        patch("finance_analysis.analysis.pipeline.StockAnalysisPipeline", return_value=pipeline) as pipeline_class,
        patch("finance_analysis.database.repositories.watch_list.get_watch_list_codes", return_value=["600519"]),
        patch.object(daily_module, "safe_record_scheduled_task_result") as recorder,
    ):
        daily_module.DailyAnalysisTaskService().run()

    pipeline_class.assert_called_once_with(config=config.return_value)
    pipeline.run.assert_called_once_with(stock_codes=["600519"])
    recorder.assert_called_once()


def test_daily_task_service_records_then_reraises_pipeline_failure():
    pipeline = MagicMock()
    pipeline.run.side_effect = RuntimeError("boom")
    with (
        patch("finance_analysis.analysis.pipeline_config.get_pipeline_config", return_value=MagicMock()),
        patch("finance_analysis.analysis.pipeline.StockAnalysisPipeline", return_value=pipeline),
        patch("finance_analysis.database.repositories.watch_list.get_watch_list_codes", return_value=["600519"]),
        patch.object(daily_module, "safe_record_scheduled_task_result") as recorder,
        pytest.raises(RuntimeError, match="boom"),
    ):
        daily_module.DailyAnalysisTaskService().run()

    recorder.assert_called_once()


def test_us_premarket_service_runs_pipeline_for_us_watch_list():
    pipeline = MagicMock()
    pipeline.run.return_value = []
    with (
        patch("finance_analysis.analysis.pipeline_config.get_pipeline_config", return_value=MagicMock()),
        patch("finance_analysis.analysis.pipeline.StockAnalysisPipeline", return_value=pipeline),
        patch(
            "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market",
            return_value=["AAPL", "TSLA"],
        ) as watchlist,
        patch.object(premarket_module, "safe_record_scheduled_task_result"),
    ):
        premarket_module.USPremarketAnalysisTaskService().run()

    watchlist.assert_called_once_with("US")
    pipeline.run.assert_called_once_with(stock_codes=["AAPL", "TSLA"])


def test_us_premarket_service_skips_empty_watch_list():
    with (
        patch(
            "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market",
            return_value=[],
        ),
        patch.object(premarket_module, "safe_record_scheduled_task_result") as recorder,
        pytest.raises(TaskSkipped),
    ):
        premarket_module.USPremarketAnalysisTaskService().run()

    recorder.assert_called_once()


def test_us_premarket_news_service_runs_domain_service():
    summary = MagicMock(symbols_count=22)
    domain_service = MagicMock()
    domain_service.run.return_value = summary
    with (
        patch("finance_analysis.analysis.pipeline_config.get_pipeline_config", return_value=MagicMock()) as config,
        patch(
            "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market",
            return_value=["AAPL", "TSLA"],
        ),
        patch(
            "finance_analysis.tasks.jobs.us_premarket_news.service.USPremarketNewsService",
            return_value=domain_service,
        ) as service_class,
    ):
        premarket_news_module.USPremarketNewsTaskService().run()

    service_class.assert_called_once_with(config=config.return_value)
    assert domain_service.run.call_args.args[0] == ["AAPL", "TSLA"]


def test_us_postmarket_service_returns_domain_summary():
    domain_service = MagicMock()
    domain_service.run.return_value.to_dict.return_value = {"market_regime": "risk_on"}
    with (
        patch("finance_analysis.analysis.pipeline_config.get_pipeline_config", return_value=MagicMock()) as config,
        patch(
            "finance_analysis.tasks.jobs.us_postmarket_review.USPostmarketReviewService",
            return_value=domain_service,
        ) as service_class,
    ):
        result = postmarket_module.USPostmarketReviewTaskService().run()

    service_class.assert_called_once_with(config=config.return_value)
    domain_service.run.assert_called_once_with(send_notification=True)
    assert result["market_regime"] == "risk_on"


def test_us_intraday_service_sleeps_and_runs_domain_service():
    summary = MagicMock(
        market_open=True,
        total_symbols=2,
        processed_symbols=2,
        stale_symbols=0,
        skipped_symbols=0,
        candidate_count=1,
        llm_candidate_count=1,
        signal_results=[],
        notification_count=0,
        timings={"duration_seconds": 1.2},
        filter_failure_counts={},
    )
    summary.to_dict.return_value = {"processed_symbols": 2}
    domain_service = MagicMock()
    domain_service.run.return_value = summary
    with (
        patch.object(us_intraday_module, "sleep_random_start_delay") as delay,
        patch("finance_analysis.analysis.pipeline_config.get_pipeline_config", return_value=MagicMock()),
        patch(
            "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market",
            return_value=["AAPL", "TSLA"],
        ),
        patch(
            "finance_analysis.tasks.jobs.us_intraday_analysis.USIntradayAnalysisService",
            return_value=domain_service,
        ),
    ):
        result = us_intraday_module.USIntradayAnalysisTaskService().run()

    delay.assert_called_once_with(task_name="美股盘中分析任务")
    domain_service.run.assert_called_once_with(["AAPL", "TSLA"])
    assert result["processed_symbols"] == 2


def test_a_share_intraday_service_sleeps_and_returns_summary():
    domain_service = MagicMock()
    domain_service.run.return_value.to_dict.return_value = {"market_regime": "divergent"}
    with (
        patch.object(a_share_module, "sleep_random_start_delay") as delay,
        patch("finance_analysis.analysis.pipeline_config.get_pipeline_config", return_value=MagicMock()),
        patch(
            "finance_analysis.tasks.jobs.a_share_intraday_analysis.AShareIntradayAnalysisService",
            return_value=domain_service,
        ),
    ):
        result = a_share_module.AShareIntradayAnalysisTaskService().run()

    delay.assert_called_once_with(task_name="A股盘中分析任务")
    domain_service.run.assert_called_once_with(send_notification=True)
    assert result["market_regime"] == "divergent"


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
        fetched_count_by_type={"earnings": 1},
        inserted_count=1,
        updated_count=0,
        skipped_duplicate_count=0,
        notification_sent_count=1,
        importance_candidate_ids=[11, 12],
    )
    summary.to_dict.return_value = {"importance_candidate_ids": [11, 12]}
    domain_service = MagicMock()
    domain_service.run.return_value = summary
    task_service = calendar_module.MarketCalendarSyncTaskService()
    with (
        patch(
            "finance_analysis.tasks.jobs.market_calendar_sync.MarketCalendarSyncService",
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

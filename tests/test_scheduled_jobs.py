# -*- coding: utf-8 -*-
"""Tests for the plain business runners behind the scheduled Celery tasks."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import finance_analysis.tasks.scheduled_jobs as scheduled_jobs


class ScheduledJobRunnerTestCase(unittest.TestCase):
    def _install_pipeline_stub(self, pipeline_cls: MagicMock) -> dict:
        fake_pipeline_module = types.ModuleType("finance_analysis.analysis.pipeline")
        fake_pipeline_module.StockAnalysisPipeline = pipeline_cls
        fake_config_module = types.ModuleType("finance_analysis.analysis.pipeline_config")
        fake_config_module.get_pipeline_config = MagicMock(return_value=MagicMock(name="config"))
        fake_repo_module = types.ModuleType("finance_analysis.database.repositories.watch_list")
        fake_repo_module.get_watch_list_codes = MagicMock(return_value=["600519"])
        fake_repo_module.get_watch_list_codes_by_market = MagicMock(return_value=[])
        return {
            "finance_analysis.analysis.pipeline": fake_pipeline_module,
            "finance_analysis.analysis.pipeline_config": fake_config_module,
            "finance_analysis.database.repositories.watch_list": fake_repo_module,
        }

    def test_daily_task_invokes_pipeline_run(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)
        fake_config = stubs["finance_analysis.analysis.pipeline_config"].get_pipeline_config.return_value

        with patch.dict(sys.modules, stubs), patch.object(
            scheduled_jobs, "_safe_record_scheduled_task_result"
        ) as record_mock:
            scheduled_jobs.run_daily_analysis()

        pipeline_cls.assert_called_once_with(config=fake_config)
        pipeline_instance.run.assert_called_once_with(stock_codes=["600519"])
        record_mock.assert_called_once()

    def test_daily_task_raises_pipeline_exception_after_recording(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_instance.run.side_effect = RuntimeError("boom")
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)

        with patch.dict(sys.modules, stubs), patch.object(
            scheduled_jobs, "_safe_record_scheduled_task_result"
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                scheduled_jobs.run_daily_analysis()

    def test_us_premarket_task_runs_pipeline_for_us_watch_list(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)
        fake_repo_module = types.ModuleType("finance_analysis.database.repositories.watch_list")
        fake_repo_module.get_watch_list_codes_by_market = MagicMock(return_value=["AAPL", "TSLA"])
        stubs["finance_analysis.database.repositories.watch_list"] = fake_repo_module

        with patch.dict(sys.modules, stubs), patch.object(
            scheduled_jobs, "_safe_record_scheduled_task_result"
        ):
            scheduled_jobs.run_us_premarket_analysis()

        fake_repo_module.get_watch_list_codes_by_market.assert_called_once_with("US")
        pipeline_instance.run.assert_called_once_with(stock_codes=["AAPL", "TSLA"])

    def test_us_premarket_task_skips_empty_us_watch_list(self) -> None:
        from finance_analysis.tasks.lifecycle import TaskSkipped

        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)
        fake_repo_module = types.ModuleType("finance_analysis.database.repositories.watch_list")
        fake_repo_module.get_watch_list_codes_by_market = MagicMock(return_value=[])
        stubs["finance_analysis.database.repositories.watch_list"] = fake_repo_module

        with patch.dict(sys.modules, stubs), patch.object(
            scheduled_jobs, "_safe_record_scheduled_task_result"
        ) as record_mock:
            with self.assertRaises(TaskSkipped):
                scheduled_jobs.run_us_premarket_analysis()

        pipeline_cls.assert_not_called()
        pipeline_instance.run.assert_not_called()
        record_mock.assert_called_once()

    def test_us_premarket_news_task_runs_service_for_us_watch_list(self) -> None:
        fake_repo_module = types.ModuleType("finance_analysis.database.repositories.watch_list")
        fake_repo_module.get_watch_list_codes_by_market = MagicMock(return_value=["AAPL", "TSLA"])
        fake_config_module = types.ModuleType("finance_analysis.analysis.pipeline_config")
        fake_config_module.get_pipeline_config = MagicMock(return_value=MagicMock(name="config"))
        fake_service_module = types.ModuleType("finance_analysis.tasks.jobs.us_premarket_news.service")
        service_instance = MagicMock()
        service_instance.run.return_value = MagicMock(symbols_count=22)
        fake_service_module.USPremarketNewsService = MagicMock(return_value=service_instance)

        stubs = {
            "finance_analysis.database.repositories.watch_list": fake_repo_module,
            "finance_analysis.analysis.pipeline_config": fake_config_module,
            "finance_analysis.tasks.jobs.us_premarket_news.service": fake_service_module,
        }
        with patch.dict(sys.modules, stubs), patch.object(
            scheduled_jobs, "_safe_record_scheduled_task_result"
        ) as record_mock:
            scheduled_jobs.run_us_premarket_news()

        fake_repo_module.get_watch_list_codes_by_market.assert_called_once_with("US")
        fake_service_module.USPremarketNewsService.assert_called_once_with(
            config=fake_config_module.get_pipeline_config.return_value
        )
        service_instance.run.assert_called_once()
        self.assertEqual(service_instance.run.call_args.args[0], ["AAPL", "TSLA"])
        record_mock.assert_not_called()

    def test_us_postmarket_review_task_runs_service_and_returns_summary(self) -> None:
        fake_config_module = types.ModuleType("finance_analysis.analysis.pipeline_config")
        fake_config_module.get_pipeline_config = MagicMock(return_value=MagicMock(name="config"))
        fake_service_module = types.ModuleType("finance_analysis.tasks.jobs.us_postmarket_review")
        service_instance = MagicMock()
        service_instance.run.return_value = MagicMock(
            to_dict=MagicMock(return_value={"trading_date": "2026-06-23", "market_regime": "risk_on"})
        )
        fake_service_module.USPostmarketReviewService = MagicMock(return_value=service_instance)

        with patch.dict(
            sys.modules,
            {
                "finance_analysis.analysis.pipeline_config": fake_config_module,
                "finance_analysis.tasks.jobs.us_postmarket_review": fake_service_module,
            },
        ):
            result = scheduled_jobs.run_us_postmarket_review()

        fake_service_module.USPostmarketReviewService.assert_called_once_with(
            config=fake_config_module.get_pipeline_config.return_value
        )
        service_instance.run.assert_called_once_with(send_notification=True)
        self.assertEqual(result["market_regime"], "risk_on")

    def test_a_share_intraday_task_runs_service_and_returns_summary(self) -> None:
        fake_config_module = types.ModuleType("finance_analysis.analysis.pipeline_config")
        fake_config_module.get_pipeline_config = MagicMock(return_value=MagicMock(name="config"))
        fake_service_module = types.ModuleType(
            "finance_analysis.tasks.jobs.a_share_intraday_analysis"
        )
        service_instance = MagicMock()
        service_instance.run.return_value = MagicMock(
            to_dict=MagicMock(return_value={"trading_date": "2026-06-24", "market_regime": "divergent"})
        )
        fake_service_module.AShareIntradayAnalysisService = MagicMock(return_value=service_instance)

        with patch.dict(
            sys.modules,
            {
                "finance_analysis.analysis.pipeline_config": fake_config_module,
                "finance_analysis.tasks.jobs.a_share_intraday_analysis": fake_service_module,
            },
        ):
            result = scheduled_jobs.run_a_share_intraday_analysis()

        fake_service_module.AShareIntradayAnalysisService.assert_called_once_with(
            config=fake_config_module.get_pipeline_config.return_value
        )
        service_instance.run.assert_called_once_with(send_notification=True)
        self.assertEqual(result["market_regime"], "divergent")

    def test_market_calendar_task_runs_service(self) -> None:
        fake_service_module = types.ModuleType("finance_analysis.tasks.jobs.market_calendar_sync")
        service_instance = MagicMock()
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
        service_instance.run.return_value = summary
        fake_service_module.MarketCalendarSyncService = MagicMock(return_value=service_instance)

        with patch.dict(sys.modules, {"finance_analysis.tasks.jobs.market_calendar_sync": fake_service_module}), patch.object(
            scheduled_jobs, "_submit_market_calendar_importance_task"
        ) as submit_mock:
            result = scheduled_jobs.run_market_calendar()

        fake_service_module.MarketCalendarSyncService.assert_called_once_with()
        service_instance.run.assert_called_once()
        submit_mock.assert_called_once_with([11, 12])
        self.assertEqual(result["importance_candidate_ids"], [11, 12])

    def test_market_calendar_importance_submit_failure_does_not_raise(self) -> None:
        task_module = types.ModuleType("finance_analysis.tasks.celery.jobs.market_calendar")
        task_module.market_calendar_importance = MagicMock()
        task_module.market_calendar_importance.apply_async.side_effect = RuntimeError("broker down")

        with patch.dict(sys.modules, {"finance_analysis.tasks.celery.jobs.market_calendar": task_module}):
            scheduled_jobs._submit_market_calendar_importance_task([1, 2])

        task_module.market_calendar_importance.apply_async.assert_called_once()


if __name__ == "__main__":
    unittest.main()

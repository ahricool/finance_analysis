# -*- coding: utf-8 -*-
"""Tests for the hardcoded APScheduler analysis scheduler."""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import finance_analysis.tasks.scheduler as scheduler_module


def _install_apscheduler_stub() -> tuple[MagicMock, MagicMock]:
    """Install a minimal ``apscheduler`` stub so the scheduler module can run.

    Returns ``(BackgroundScheduler, CronTrigger)`` mocks injected into ``sys.modules``.
    """
    pkg = types.ModuleType("apscheduler")
    schedulers_pkg = types.ModuleType("apscheduler.schedulers")
    background_mod = types.ModuleType("apscheduler.schedulers.background")
    triggers_pkg = types.ModuleType("apscheduler.triggers")
    cron_mod = types.ModuleType("apscheduler.triggers.cron")
    combining_mod = types.ModuleType("apscheduler.triggers.combining")

    background_scheduler = MagicMock(name="BackgroundScheduler")
    cron_trigger = MagicMock(name="CronTrigger")
    or_trigger = MagicMock(name="OrTrigger")
    background_mod.BackgroundScheduler = background_scheduler
    cron_mod.CronTrigger = cron_trigger
    combining_mod.OrTrigger = or_trigger

    sys.modules.update(
        {
            "apscheduler": pkg,
            "apscheduler.schedulers": schedulers_pkg,
            "apscheduler.schedulers.background": background_mod,
            "apscheduler.triggers": triggers_pkg,
            "apscheduler.triggers.cron": cron_mod,
            "apscheduler.triggers.combining": combining_mod,
        }
    )
    return background_scheduler, cron_trigger, or_trigger


class HardcodedSchedulerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._modules_snapshot = {
            name: sys.modules.get(name)
            for name in (
                "apscheduler",
                "apscheduler.schedulers",
                "apscheduler.schedulers.background",
                "apscheduler.triggers",
                "apscheduler.triggers.cron",
                "apscheduler.triggers.combining",
            )
        }
        (
            self.background_scheduler_cls,
            self.cron_trigger_cls,
            self.or_trigger_cls,
        ) = _install_apscheduler_stub()

    def tearDown(self) -> None:
        for name, mod in self._modules_snapshot.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_start_registers_daily_cron_with_hardcoded_time(self) -> None:
        scheduler_instance = MagicMock()
        scheduler_instance.get_job.return_value = MagicMock(next_run_time=None)
        self.background_scheduler_cls.return_value = scheduler_instance

        with patch.object(scheduler_module, "RUN_IMMEDIATELY_ON_STARTUP", False):
            returned = scheduler_module.start_embedded_analysis_scheduler()

        self.assertIs(returned, scheduler_instance)
        # 6 single-cron jobs + 2 cron triggers composed into the A-share OrTrigger.
        self.assertEqual(self.cron_trigger_cls.call_count, 8)
        self.assertEqual(self.or_trigger_cls.call_count, 1)
        self.cron_trigger_cls.assert_any_call(
            hour=scheduler_module.DAILY_SCHEDULE_HOUR,
            minute=scheduler_module.DAILY_SCHEDULE_MINUTE,
            timezone=scheduler_module.SCHEDULE_TIMEZONE,
        )
        self.cron_trigger_cls.assert_any_call(
            hour=scheduler_module.MARKET_CALENDAR_SCHEDULE_HOUR,
            minute=scheduler_module.MARKET_CALENDAR_SCHEDULE_MINUTE,
            timezone=scheduler_module.SCHEDULE_TIMEZONE,
        )
        self.cron_trigger_cls.assert_any_call(
            hour=scheduler_module.US_PREMARKET_NEWS_SCHEDULE_HOUR,
            minute=scheduler_module.US_PREMARKET_NEWS_SCHEDULE_MINUTE,
            timezone=scheduler_module.SCHEDULE_TIMEZONE,
        )
        self.cron_trigger_cls.assert_any_call(
            hour=scheduler_module.US_PREMARKET_SCHEDULE_HOUR,
            minute=scheduler_module.US_PREMARKET_SCHEDULE_MINUTE,
            timezone=scheduler_module.SCHEDULE_TIMEZONE,
        )
        self.cron_trigger_cls.assert_any_call(
            minute=f"*/{scheduler_module.INTRADAY_ANALYSIS_INTERVAL_MINUTES}",
            timezone=scheduler_module.SCHEDULE_TIMEZONE,
        )
        self.cron_trigger_cls.assert_any_call(
            hour=scheduler_module.US_POSTMARKET_REVIEW_SCHEDULE_HOUR,
            minute=scheduler_module.US_POSTMARKET_REVIEW_SCHEDULE_MINUTE,
            timezone=scheduler_module.US_POSTMARKET_REVIEW_TIMEZONE,
        )
        self.assertEqual(scheduler_instance.add_job.call_count, 7)
        add_job_kwargs = scheduler_instance.add_job.call_args_list[0].kwargs
        self.assertEqual(add_job_kwargs["id"], "analysis_daily")
        self.assertTrue(add_job_kwargs["replace_existing"])
        self.assertEqual(add_job_kwargs["max_instances"], 1)
        self.assertTrue(add_job_kwargs["coalesce"])
        us_add_job_kwargs = scheduler_instance.add_job.call_args_list[1].kwargs
        self.assertEqual(us_add_job_kwargs["id"], "market_calendar")
        self.assertTrue(us_add_job_kwargs["replace_existing"])
        self.assertEqual(us_add_job_kwargs["max_instances"], 1)
        self.assertTrue(us_add_job_kwargs["coalesce"])
        us_add_job_kwargs = scheduler_instance.add_job.call_args_list[2].kwargs
        self.assertEqual(us_add_job_kwargs["id"], "analysis_us_premarket_news")
        self.assertTrue(us_add_job_kwargs["replace_existing"])
        self.assertEqual(us_add_job_kwargs["max_instances"], 1)
        self.assertTrue(us_add_job_kwargs["coalesce"])
        us_analysis_add_job_kwargs = scheduler_instance.add_job.call_args_list[3].kwargs
        self.assertEqual(us_analysis_add_job_kwargs["id"], "analysis_us_premarket")
        self.assertTrue(us_analysis_add_job_kwargs["replace_existing"])
        self.assertEqual(us_analysis_add_job_kwargs["max_instances"], 1)
        self.assertTrue(us_analysis_add_job_kwargs["coalesce"])
        us_intraday_add_job_kwargs = scheduler_instance.add_job.call_args_list[4].kwargs
        self.assertEqual(us_intraday_add_job_kwargs["id"], "analysis_us_intraday")
        self.assertTrue(us_intraday_add_job_kwargs["replace_existing"])
        self.assertEqual(us_intraday_add_job_kwargs["max_instances"], 1)
        self.assertTrue(us_intraday_add_job_kwargs["coalesce"])
        us_postmarket_add_job_kwargs = scheduler_instance.add_job.call_args_list[5].kwargs
        self.assertEqual(us_postmarket_add_job_kwargs["id"], "analysis_us_postmarket_review")
        self.assertTrue(us_postmarket_add_job_kwargs["replace_existing"])
        self.assertEqual(us_postmarket_add_job_kwargs["max_instances"], 1)
        self.assertTrue(us_postmarket_add_job_kwargs["coalesce"])
        self.assertEqual(us_postmarket_add_job_kwargs["misfire_grace_time"], 1800)
        a_share_intraday_add_job_kwargs = scheduler_instance.add_job.call_args_list[6].kwargs
        self.assertEqual(a_share_intraday_add_job_kwargs["id"], "analysis_a_share_intraday")
        self.assertTrue(a_share_intraday_add_job_kwargs["replace_existing"])
        self.assertEqual(a_share_intraday_add_job_kwargs["max_instances"], 1)
        self.assertTrue(a_share_intraday_add_job_kwargs["coalesce"])
        scheduler_instance.start.assert_called_once()

    def test_start_registers_premarket_analysis_without_changing_job_options(self) -> None:
        scheduler_instance = MagicMock()
        scheduler_instance.get_job.return_value = MagicMock(next_run_time=None)
        self.background_scheduler_cls.return_value = scheduler_instance

        with patch.object(scheduler_module, "RUN_IMMEDIATELY_ON_STARTUP", False):
            scheduler_module.start_embedded_analysis_scheduler()

        us_add_job_kwargs = scheduler_instance.add_job.call_args_list[3].kwargs
        self.assertEqual(us_add_job_kwargs["id"], "analysis_us_premarket")
        self.assertTrue(us_add_job_kwargs["replace_existing"])
        self.assertEqual(us_add_job_kwargs["max_instances"], 1)
        self.assertTrue(us_add_job_kwargs["coalesce"])

    def test_us_postmarket_review_definition_is_exposed_for_task_center(self) -> None:
        definitions = {
            item.job_id: item
            for item in scheduler_module.get_scheduled_task_definitions()
        }

        definition = definitions["analysis_us_postmarket_review"]
        self.assertEqual(definition.name, "美股收盘复盘")
        self.assertEqual(definition.task_type, "scheduled_us_postmarket_review")
        self.assertEqual(definition.timezone, "America/New_York")
        self.assertEqual(definition.schedule, "美股交易日 16:30 America/New_York")
        self.assertTrue(definition.allow_manual_run)

    def test_start_runs_task_immediately_when_flag_enabled(self) -> None:
        scheduler_instance = MagicMock()
        scheduler_instance.get_job.return_value = MagicMock(next_run_time=None)
        self.background_scheduler_cls.return_value = scheduler_instance

        with patch.object(scheduler_module, "RUN_IMMEDIATELY_ON_STARTUP", True), \
             patch.object(scheduler_module, "_daily_analysis_task") as task_mock, \
             patch.object(scheduler_module, "_market_calendar_task") as market_calendar_task_mock:
            scheduler_module.start_embedded_analysis_scheduler()

        task_mock.assert_called_once()
        market_calendar_task_mock.assert_not_called()

    def test_shutdown_waits_for_running_jobs(self) -> None:
        scheduler_instance = MagicMock()
        scheduler_module.shutdown_embedded_analysis_scheduler(scheduler_instance)
        scheduler_instance.shutdown.assert_called_once_with(wait=True)

    def test_shutdown_noop_when_scheduler_is_none(self) -> None:
        scheduler_module.shutdown_embedded_analysis_scheduler(None)

    def _install_pipeline_stub(self, pipeline_cls: MagicMock) -> dict:
        """Inject stub modules so ``_daily_analysis_task`` can import without dotenv."""
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
            scheduler_module, "_safe_record_scheduled_task_result"
        ) as record_mock:
            scheduler_module._daily_analysis_task()

        pipeline_cls.assert_called_once_with(config=fake_config)
        pipeline_instance.run.assert_called_once_with(stock_codes=["600519"])
        record_mock.assert_called_once()

    def test_daily_task_raises_pipeline_exception_after_recording(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_instance.run.side_effect = RuntimeError("boom")
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)

        with patch.dict(sys.modules, stubs), patch.object(
            scheduler_module, "_safe_record_scheduled_task_result"
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                scheduler_module._daily_analysis_task()

    def test_us_premarket_task_runs_pipeline_for_us_watch_list(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)
        fake_repo_module = types.ModuleType("finance_analysis.database.repositories.watch_list")
        fake_repo_module.get_watch_list_codes_by_market = MagicMock(return_value=["AAPL", "TSLA"])
        stubs["finance_analysis.database.repositories.watch_list"] = fake_repo_module

        with patch.dict(sys.modules, stubs), patch.object(
            scheduler_module, "_safe_record_scheduled_task_result"
        ):
            scheduler_module._us_premarket_analysis_task()

        fake_repo_module.get_watch_list_codes_by_market.assert_called_once_with("US")
        pipeline_instance.run.assert_called_once_with(stock_codes=["AAPL", "TSLA"])

    def test_us_premarket_task_skips_empty_us_watch_list(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)
        fake_repo_module = types.ModuleType("finance_analysis.database.repositories.watch_list")
        fake_repo_module.get_watch_list_codes_by_market = MagicMock(return_value=[])
        stubs["finance_analysis.database.repositories.watch_list"] = fake_repo_module

        with patch.dict(sys.modules, stubs), patch.object(
            scheduler_module, "_safe_record_scheduled_task_result"
        ) as record_mock:
            scheduler_module._us_premarket_analysis_task()

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
            scheduler_module, "_safe_record_scheduled_task_result"
        ) as record_mock:
            scheduler_module._us_premarket_news_task()

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
            result = scheduler_module._us_postmarket_review_task()

        fake_service_module.USPostmarketReviewService.assert_called_once_with(
            config=fake_config_module.get_pipeline_config.return_value
        )
        service_instance.run.assert_called_once_with(send_notification=True)
        self.assertEqual(result["market_regime"], "risk_on")

    def test_a_share_intraday_definition_is_exposed_for_task_center(self) -> None:
        definitions = {
            item.job_id: item
            for item in scheduler_module.get_scheduled_task_definitions()
        }

        definition = definitions["analysis_a_share_intraday"]
        self.assertEqual(definition.name, "A股盘中分析")
        self.assertEqual(definition.task_type, "scheduled_a_share_intraday")
        self.assertEqual(definition.timezone, "Asia/Shanghai")
        self.assertTrue(definition.allow_manual_run)

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
            result = scheduler_module._a_share_intraday_analysis_task()

        fake_service_module.AShareIntradayAnalysisService.assert_called_once_with(
            config=fake_config_module.get_pipeline_config.return_value
        )
        service_instance.run.assert_called_once_with(send_notification=True)
        self.assertEqual(result["market_regime"], "divergent")

    def test_market_calendar_task_runs_service(self) -> None:
        fake_service_module = types.ModuleType("finance_analysis.tasks.jobs.market_calendar_sync")
        service_instance = MagicMock()
        service_instance.run.return_value = MagicMock(
            all_interfaces_failed=False,
            fetched_count_by_type={"earnings": 1},
            inserted_count=1,
            updated_count=0,
            skipped_duplicate_count=0,
            notification_sent_count=1,
        )
        fake_service_module.MarketCalendarSyncService = MagicMock(return_value=service_instance)

        with patch.dict(sys.modules, {"finance_analysis.tasks.jobs.market_calendar_sync": fake_service_module}):
            scheduler_module._market_calendar_task()

        fake_service_module.MarketCalendarSyncService.assert_called_once_with()
        service_instance.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()

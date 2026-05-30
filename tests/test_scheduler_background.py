# -*- coding: utf-8 -*-
"""Tests for the hardcoded APScheduler analysis scheduler."""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import src.scheduler as scheduler_module


def _install_apscheduler_stub() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Install a minimal ``apscheduler`` stub so the scheduler module can run.

    Returns ``(BackgroundScheduler, CronTrigger, IntervalTrigger)`` mocks injected into ``sys.modules``.
    """
    pkg = types.ModuleType("apscheduler")
    schedulers_pkg = types.ModuleType("apscheduler.schedulers")
    background_mod = types.ModuleType("apscheduler.schedulers.background")
    triggers_pkg = types.ModuleType("apscheduler.triggers")
    cron_mod = types.ModuleType("apscheduler.triggers.cron")
    interval_mod = types.ModuleType("apscheduler.triggers.interval")

    background_scheduler = MagicMock(name="BackgroundScheduler")
    cron_trigger = MagicMock(name="CronTrigger")
    interval_trigger = MagicMock(name="IntervalTrigger")
    background_mod.BackgroundScheduler = background_scheduler
    cron_mod.CronTrigger = cron_trigger
    interval_mod.IntervalTrigger = interval_trigger

    sys.modules.update(
        {
            "apscheduler": pkg,
            "apscheduler.schedulers": schedulers_pkg,
            "apscheduler.schedulers.background": background_mod,
            "apscheduler.triggers": triggers_pkg,
            "apscheduler.triggers.cron": cron_mod,
            "apscheduler.triggers.interval": interval_mod,
        }
    )
    return background_scheduler, cron_trigger, interval_trigger


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
                "apscheduler.triggers.interval",
            )
        }
        (
            self.background_scheduler_cls,
            self.cron_trigger_cls,
            self.interval_trigger_cls,
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
        self.assertEqual(self.cron_trigger_cls.call_count, 2)
        self.assertEqual(self.interval_trigger_cls.call_count, 2)
        self.cron_trigger_cls.assert_any_call(
            hour=scheduler_module.DAILY_SCHEDULE_HOUR,
            minute=scheduler_module.DAILY_SCHEDULE_MINUTE,
            timezone=scheduler_module.SCHEDULE_TIMEZONE,
        )
        self.cron_trigger_cls.assert_any_call(
            hour=scheduler_module.US_PREMARKET_SCHEDULE_HOUR,
            minute=scheduler_module.US_PREMARKET_SCHEDULE_MINUTE,
            timezone=scheduler_module.SCHEDULE_TIMEZONE,
        )
        self.interval_trigger_cls.assert_any_call(
            minutes=scheduler_module.INTRADAY_ANALYSIS_INTERVAL_MINUTES,
            timezone=scheduler_module.SCHEDULE_TIMEZONE,
        )
        self.assertEqual(scheduler_instance.add_job.call_count, 4)
        add_job_kwargs = scheduler_instance.add_job.call_args_list[0].kwargs
        self.assertEqual(add_job_kwargs["id"], "analysis_daily")
        self.assertTrue(add_job_kwargs["replace_existing"])
        self.assertEqual(add_job_kwargs["max_instances"], 1)
        self.assertTrue(add_job_kwargs["coalesce"])
        us_add_job_kwargs = scheduler_instance.add_job.call_args_list[1].kwargs
        self.assertEqual(us_add_job_kwargs["id"], "analysis_us_premarket")
        self.assertTrue(us_add_job_kwargs["replace_existing"])
        self.assertEqual(us_add_job_kwargs["max_instances"], 1)
        self.assertTrue(us_add_job_kwargs["coalesce"])
        us_intraday_kwargs = scheduler_instance.add_job.call_args_list[2].kwargs
        self.assertEqual(us_intraday_kwargs["id"], "analysis_us_intraday")
        cn_intraday_kwargs = scheduler_instance.add_job.call_args_list[3].kwargs
        self.assertEqual(cn_intraday_kwargs["id"], "analysis_cn_intraday")
        scheduler_instance.start.assert_called_once()

    def test_start_runs_task_immediately_when_flag_enabled(self) -> None:
        scheduler_instance = MagicMock()
        scheduler_instance.get_job.return_value = MagicMock(next_run_time=None)
        self.background_scheduler_cls.return_value = scheduler_instance

        with patch.object(scheduler_module, "RUN_IMMEDIATELY_ON_STARTUP", True), \
             patch.object(scheduler_module, "_daily_analysis_task") as task_mock:
            scheduler_module.start_embedded_analysis_scheduler()

        task_mock.assert_called_once()

    def test_intraday_placeholder_tasks_do_not_run_pipeline(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)

        with patch.dict(sys.modules, stubs):
            scheduler_module._us_intraday_analysis_task()
            scheduler_module._cn_intraday_analysis_task()

        pipeline_cls.assert_not_called()
        pipeline_instance.run.assert_not_called()

    def test_shutdown_waits_for_running_jobs(self) -> None:
        scheduler_instance = MagicMock()
        scheduler_module.shutdown_embedded_analysis_scheduler(scheduler_instance)
        scheduler_instance.shutdown.assert_called_once_with(wait=True)

    def test_shutdown_noop_when_scheduler_is_none(self) -> None:
        scheduler_module.shutdown_embedded_analysis_scheduler(None)

    def _install_pipeline_stub(self, pipeline_cls: MagicMock) -> dict:
        """Inject stub modules so ``_daily_analysis_task`` can import without dotenv."""
        fake_pipeline_module = types.ModuleType("src.core.pipeline")
        fake_pipeline_module.StockAnalysisPipeline = pipeline_cls
        fake_config_module = types.ModuleType("src.config")
        fake_config_module.get_config = MagicMock(return_value=MagicMock(name="config"))
        return {
            "src.core.pipeline": fake_pipeline_module,
            "src.config": fake_config_module,
        }

    def test_daily_task_invokes_pipeline_run(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)
        fake_config = stubs["src.config"].get_config.return_value

        with patch.dict(sys.modules, stubs):
            scheduler_module._daily_analysis_task()

        pipeline_cls.assert_called_once_with(config=fake_config)
        pipeline_instance.run.assert_called_once_with()

    def test_daily_task_swallows_pipeline_exception(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_instance.run.side_effect = RuntimeError("boom")
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)

        with patch.dict(sys.modules, stubs):
            scheduler_module._daily_analysis_task()

    def test_us_premarket_task_runs_pipeline_for_us_watch_list(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)
        fake_repo_module = types.ModuleType("src.repositories.watch_list_repo")
        fake_repo_module.get_watch_list_codes_by_market = MagicMock(return_value=["AAPL", "TSLA"])
        stubs["src.repositories.watch_list_repo"] = fake_repo_module

        with patch.dict(sys.modules, stubs):
            scheduler_module._us_premarket_analysis_task()

        fake_repo_module.get_watch_list_codes_by_market.assert_called_once_with("US")
        pipeline_instance.run.assert_called_once_with(stock_codes=["AAPL", "TSLA"])

    def test_us_premarket_task_skips_empty_us_watch_list(self) -> None:
        pipeline_instance = MagicMock()
        pipeline_cls = MagicMock(return_value=pipeline_instance)
        stubs = self._install_pipeline_stub(pipeline_cls)
        fake_repo_module = types.ModuleType("src.repositories.watch_list_repo")
        fake_repo_module.get_watch_list_codes_by_market = MagicMock(return_value=[])
        stubs["src.repositories.watch_list_repo"] = fake_repo_module

        with patch.dict(sys.modules, stubs):
            scheduler_module._us_premarket_analysis_task()

        pipeline_cls.assert_not_called()
        pipeline_instance.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

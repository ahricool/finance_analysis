# -*- coding: utf-8 -*-
"""Tests for APScheduler-based analysis scheduler."""

import unittest
from unittest.mock import MagicMock, patch


class SchedulerBackgroundTaskTestCase(unittest.TestCase):
    def test_pending_spec_register_and_pop(self) -> None:
        from src.scheduler import (
            AnalysisScheduleSpec,
            pop_pending_analysis_schedule,
            register_pending_analysis_schedule,
        )

        register_pending_analysis_schedule(
            AnalysisScheduleSpec(
                task=lambda: None,
                schedule_time="18:00",
                run_immediately=False,
            )
        )
        popped = pop_pending_analysis_schedule()
        self.assertIsNotNone(popped)
        self.assertEqual(popped.schedule_time, "18:00")
        self.assertIsNone(pop_pending_analysis_schedule())

    def test_bundle_rejects_invalid_initial_schedule_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "25:99"):
            from src.scheduler import AnalysisScheduleSpec, AnalysisSchedulerBundle

            AnalysisSchedulerBundle(
                AnalysisScheduleSpec(task=lambda: None, schedule_time="25:99", run_immediately=False)
            )

    def test_run_with_schedule_delegates_to_standalone(self) -> None:
        captured = {}

        def fake_standalone(spec) -> None:
            captured["spec"] = spec

        with patch("src.scheduler.run_standalone_analysis_scheduler", side_effect=fake_standalone):
            from src.scheduler import run_with_schedule

            run_with_schedule(lambda: None, schedule_time="09:15", run_immediately=False)

        self.assertEqual(captured["spec"].schedule_time, "09:15")
        self.assertFalse(captured["spec"].run_immediately)

    def test_refresh_daily_reschedules_when_provider_returns_new_time(self) -> None:
        from src.scheduler import AnalysisScheduleSpec, AnalysisSchedulerBundle

        spec = AnalysisScheduleSpec(
            task=lambda: None,
            schedule_time="18:00",
            run_immediately=False,
            schedule_time_provider=lambda: "09:30",
        )
        bundle = object.__new__(AnalysisSchedulerBundle)
        bundle._spec = spec
        bundle.schedule_time = "18:00"
        bundle._schedule_time_provider = spec.schedule_time_provider
        bundle._apply_daily_cron = MagicMock()

        bundle._refresh_daily_schedule_if_needed()

        bundle._apply_daily_cron.assert_called_once_with("09:30", log_reschedule=True)

    def test_refresh_daily_keeps_time_when_provider_returns_invalid(self) -> None:
        from src.scheduler import AnalysisScheduleSpec, AnalysisSchedulerBundle

        spec = AnalysisScheduleSpec(
            task=lambda: None,
            schedule_time="18:00",
            run_immediately=False,
            schedule_time_provider=lambda: "25:99",
        )
        bundle = object.__new__(AnalysisSchedulerBundle)
        bundle._spec = spec
        bundle.schedule_time = "18:00"
        bundle._schedule_time_provider = spec.schedule_time_provider
        bundle._apply_daily_cron = MagicMock()

        bundle._refresh_daily_schedule_if_needed()

        bundle._apply_daily_cron.assert_not_called()
        self.assertEqual(bundle.schedule_time, "18:00")

    def test_refresh_daily_keeps_time_when_provider_raises(self) -> None:
        from src.scheduler import AnalysisScheduleSpec, AnalysisSchedulerBundle

        calls = {"n": 0}

        def provider():
            calls["n"] += 1
            if calls["n"] == 1:
                return "09:30"
            raise RuntimeError("boom")

        spec = AnalysisScheduleSpec(
            task=lambda: None,
            schedule_time="18:00",
            run_immediately=False,
            schedule_time_provider=provider,
        )
        bundle = object.__new__(AnalysisSchedulerBundle)
        bundle._spec = spec
        bundle.schedule_time = "18:00"
        bundle._schedule_time_provider = provider
        bundle._apply_daily_cron = MagicMock(
            side_effect=lambda hh_mm, **kwargs: setattr(bundle, "schedule_time", hh_mm)
        )

        bundle._refresh_daily_schedule_if_needed()
        bundle._apply_daily_cron.assert_called_once_with("09:30", log_reschedule=True)

        bundle._apply_daily_cron.reset_mock()
        bundle._refresh_daily_schedule_if_needed()
        bundle._apply_daily_cron.assert_not_called()
        self.assertEqual(bundle.schedule_time, "09:30")


if __name__ == "__main__":
    unittest.main()

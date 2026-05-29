# -*- coding: utf-8 -*-
"""Tests for APScheduler-based analysis scheduler."""

import unittest
from unittest.mock import MagicMock, patch


class SchedulerBackgroundTaskTestCase(unittest.TestCase):
    def test_try_build_from_config_disabled(self) -> None:
        with patch("src.config.get_config") as mock_gc:
            mock_gc.return_value = MagicMock(schedule_enabled=False)
            from src.scheduler import try_build_analysis_schedule_spec_from_config

            self.assertIsNone(try_build_analysis_schedule_spec_from_config())

    def test_bundle_rejects_invalid_initial_schedule_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "25:99"):
            from src.scheduler import AnalysisScheduleSpec, AnalysisSchedulerBundle

            AnalysisSchedulerBundle(
                AnalysisScheduleSpec(task=lambda: None, schedule_time="25:99", run_immediately=False)
            )

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

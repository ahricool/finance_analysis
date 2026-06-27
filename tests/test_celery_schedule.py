# -*- coding: utf-8 -*-
"""Tests for the Celery scheduling registry, Beat schedule, and next-run math."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.cron import LocalizedCrontab, compute_next_run, next_run_for_crontab
from finance_analysis.tasks.celery.schedule import (
    ALL_QUEUES,
    build_beat_schedule,
    build_task_routes,
    celery_task_name,
    get_scheduled_task_definition,
    get_scheduled_task_definitions,
)

EXPECTED_JOBS = {
    "analysis_daily": ("scheduled_daily", "Asia/Shanghai"),
    "market_calendar": ("scheduled_market_calendar", "Asia/Shanghai"),
    "analysis_us_premarket_news": ("scheduled_us_premarket_news", "Asia/Shanghai"),
    "analysis_us_premarket": ("scheduled_us_premarket", "Asia/Shanghai"),
    "analysis_us_intraday": ("scheduled_us_intraday", "America/New_York"),
    "analysis_us_postmarket_review": ("scheduled_us_postmarket_review", "America/New_York"),
    "analysis_a_share_intraday": ("scheduled_a_share_intraday", "Asia/Shanghai"),
}


def test_registry_preserves_job_id_task_type_and_timezone():
    definitions = {d.job_id: d for d in get_scheduled_task_definitions()}
    assert set(definitions) == set(EXPECTED_JOBS)
    for job_id, (task_type, tz) in EXPECTED_JOBS.items():
        definition = definitions[job_id]
        assert definition.task_type == task_type
        assert definition.timezone == tz
        assert definition.allow_manual_run is True
        assert definition.celery_task_name == celery_task_name(job_id)


def test_all_original_jobs_enter_beat_schedule():
    schedule = build_beat_schedule()
    task_names = {entry["task"] for entry in schedule.values()}
    for job_id in EXPECTED_JOBS:
        assert celery_task_name(job_id) in task_names
    a_share_entries = [k for k in schedule if k.startswith("analysis_a_share_intraday")]
    assert len(a_share_entries) == 5
    us_intraday_entries = [k for k in schedule if k.startswith("analysis_us_intraday")]
    assert len(us_intraday_entries) == 2


def test_beat_entries_carry_scheduler_kwargs_queue_and_expires():
    schedule = build_beat_schedule()
    daily = schedule["analysis_daily"]
    assert daily["kwargs"]["scheduler_job_id"] == "analysis_daily"
    assert daily["kwargs"]["_trigger_source"] == "scheduler"
    assert daily["options"]["queue"] == "analysis"
    assert daily["options"]["expires"] > 0


def test_intraday_expires_is_short():
    definition = get_scheduled_task_definition("analysis_us_intraday")
    assert definition.expires <= 10 * 60


def test_us_intraday_uses_new_york_offset_windows():
    definition = get_scheduled_task_definition("analysis_us_intraday")

    assert definition.timezone == "America/New_York"
    assert definition.expires == 4 * 60
    schedules = {(item.hour, item.minute, item.day_of_week, item.timezone) for item in definition.schedules}
    assert ("9", "45,50,55", "mon-fri", "America/New_York") in schedules
    assert ("10-15", "*/5", "mon-fri", "America/New_York") in schedules
    assert "每5分钟" in definition.schedule_text


def test_a_share_intraday_uses_five_minute_windows_and_skips_lunch():
    definition = get_scheduled_task_definition("analysis_a_share_intraday")

    assert definition.timezone == "Asia/Shanghai"
    schedules = {(item.hour, item.minute, item.day_of_week, item.timezone) for item in definition.schedules}
    assert ("9", "45,50,55", "mon-fri", "Asia/Shanghai") in schedules
    assert ("10", "*/5", "mon-fri", "Asia/Shanghai") in schedules
    assert ("11", "0,5,10,15,20,25,30", "mon-fri", "Asia/Shanghai") in schedules
    assert ("13-14", "*/5", "mon-fri", "Asia/Shanghai") in schedules
    assert ("15", "0", "mon-fri", "Asia/Shanghai") in schedules
    assert "午休不运行" in definition.schedule_text


def test_all_scheduled_celery_tasks_are_registered():
    celery_app.loader.import_default_modules()
    for job_id in EXPECTED_JOBS:
        assert celery_task_name(job_id) in celery_app.tasks


def test_worker_disable_prefetch_is_true():
    assert celery_app.conf.worker_disable_prefetch is True


def test_task_routes_match_worker_queues():
    routes = build_task_routes()
    routed_queues = {route["queue"] for route in routes.values()}
    assert routed_queues.issubset(set(ALL_QUEUES))
    # Every scheduled task is routed.
    for job_id in EXPECTED_JOBS:
        assert celery_task_name(job_id) in routes


def test_acks_late_is_not_globally_enabled():
    assert not celery_app.conf.task_acks_late


def test_single_cron_next_run_is_timezone_aware_utc():
    cron = LocalizedCrontab(minute="0", hour="18", tz="Asia/Shanghai")
    now = datetime(2026, 6, 24, 0, 0, tzinfo=timezone.utc)  # 08:00 Shanghai
    nxt = next_run_for_crontab(cron, "Asia/Shanghai", after=now)
    assert nxt is not None
    assert nxt.tzinfo is not None
    # 18:00 Shanghai == 10:00 UTC same day.
    assert nxt == datetime(2026, 6, 24, 10, 0, tzinfo=timezone.utc)


def test_next_run_rolls_over_to_next_day():
    cron = LocalizedCrontab(minute="0", hour="9", tz="Asia/Shanghai")
    now = datetime(2026, 6, 24, 5, 0, tzinfo=timezone.utc)  # 13:00 Shanghai, past 09:00
    nxt = next_run_for_crontab(cron, "Asia/Shanghai", after=now)
    # Next 09:00 Shanghai is the following day == 01:00 UTC next day.
    assert nxt == datetime(2026, 6, 25, 1, 0, tzinfo=timezone.utc)


def test_a_share_window_skips_weekend():
    definition = get_scheduled_task_definition("analysis_a_share_intraday")
    # Friday 2026-06-26 16:00 Shanghai (08:00 UTC) -> next is Monday morning.
    friday_evening = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)
    nxt = definition.next_run_time(now=friday_evening)
    local = nxt.astimezone(ZoneInfo("Asia/Shanghai"))
    assert local.isoweekday() == 1  # Monday
    assert (local.hour, local.minute) == (9, 45)


def test_multi_cron_takes_earliest_window():
    definition = get_scheduled_task_definition("analysis_a_share_intraday")
    # Monday 2026-06-22 12:00 Shanghai (04:00 UTC): morning window finished at
    # 11:45, so the next fire is the afternoon window opener at 13:00.
    monday_noon = datetime(2026, 6, 22, 4, 0, tzinfo=timezone.utc)
    nxt = definition.next_run_time(now=monday_noon)
    local = nxt.astimezone(ZoneInfo("Asia/Shanghai"))
    assert (local.hour, local.minute) == (13, 0)


def test_us_postmarket_review_follows_new_york_dst():
    definition = get_scheduled_task_definition("analysis_us_postmarket_review")

    # Summer (EDT, UTC-4): 16:30 New York == 20:30 UTC.
    summer = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    summer_next = definition.next_run_time(now=summer)
    assert summer_next == datetime(2026, 7, 1, 20, 30, tzinfo=timezone.utc)

    # Winter (EST, UTC-5): 16:30 New York == 21:30 UTC.
    winter = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    winter_next = definition.next_run_time(now=winter)
    assert winter_next == datetime(2026, 1, 5, 21, 30, tzinfo=timezone.utc)


def test_us_intraday_schedule_follows_new_york_dst():
    definition = get_scheduled_task_definition("analysis_us_intraday")

    summer = datetime(2026, 7, 1, 13, 44, tzinfo=timezone.utc)
    winter = datetime(2026, 1, 5, 14, 44, tzinfo=timezone.utc)

    assert definition.next_run_time(now=summer) == datetime(2026, 7, 1, 13, 45, tzinfo=timezone.utc)
    assert definition.next_run_time(now=winter) == datetime(2026, 1, 5, 14, 45, tzinfo=timezone.utc)


def test_compute_next_run_handles_localized_per_schedule_timezone():
    ny = LocalizedCrontab(minute="30", hour="16", tz="America/New_York")
    summer = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    nxt = compute_next_run([ny], "Asia/Shanghai", now=summer)
    assert nxt == datetime(2026, 7, 1, 20, 30, tzinfo=timezone.utc)


def test_scheduled_celery_tasks_are_lifecycle_tracked():
    from finance_analysis.tasks.celery.jobs.scheduled import SCHEDULED_CELERY_TASKS
    from finance_analysis.tasks.lifecycle import is_tracked_callable

    assert set(SCHEDULED_CELERY_TASKS) == set(EXPECTED_JOBS)
    for task in SCHEDULED_CELERY_TASKS.values():
        assert is_tracked_callable(task)


def test_before_publish_creates_single_pending_record_with_scheduler_metadata():
    from unittest.mock import patch

    from finance_analysis.tasks.celery import app as app_module

    events = []

    class _RecordingService:
        def create_pending(self, **kwargs):
            events.append(kwargs)

    with patch.object(app_module, "get_task_lifecycle_service", return_value=_RecordingService()):
        app_module._create_pending_task_record(
            sender="scheduled.analysis_daily",
            headers={"id": "tid-1"},
            body=([], {"scheduler_job_id": "analysis_daily", "_trigger_source": "scheduler"}, {}),
        )

    assert len(events) == 1
    event = events[0]
    assert event["task_id"] == "tid-1"
    metadata = event["metadata"]
    assert metadata.task_type == "scheduled_daily"
    assert metadata.source == "celery"
    assert metadata.scheduler_job_id == "analysis_daily"
    assert metadata.trigger_source == "scheduler"
    # No dedupe_key here: manual runs pre-create the record with it, and the
    # auto-pending path only resolves uniqueness by task_id.
    assert "dedupe_key" not in event


def test_before_publish_carries_manual_trigger_metadata():
    from unittest.mock import patch

    from finance_analysis.tasks.celery import app as app_module

    events = []

    class _RecordingService:
        def create_pending(self, **kwargs):
            events.append(kwargs)

    with patch.object(app_module, "get_task_lifecycle_service", return_value=_RecordingService()):
        app_module._create_pending_task_record(
            sender="scheduled.analysis_us_postmarket_review",
            headers={"id": "tid-2"},
            body=(
                [],
                {
                    "scheduler_job_id": "analysis_us_postmarket_review",
                    "_trigger_source": "manual",
                    "_triggered_by_uid": 42,
                },
                {},
            ),
        )

    assert len(events) == 1
    metadata = events[0]["metadata"]
    assert metadata.trigger_source == "manual"
    assert metadata.triggered_by_uid == 42

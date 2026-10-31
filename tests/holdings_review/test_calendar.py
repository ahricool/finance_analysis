from datetime import datetime

from finance_analysis.holdings_review.calendar import default_dates, review_window
from finance_analysis.tasks.celery.schedule import get_scheduled_task_definition


def test_normal_windows_and_early_close_follow_exchange_calendar():
    assert review_window("CN", datetime.fromisoformat("2026-10-30T14:09:00+08:00")) is None
    assert review_window("CN", datetime.fromisoformat("2026-10-30T14:10:00+08:00"))
    assert review_window("CN", datetime.fromisoformat("2026-10-30T14:25:00+08:00")) is None
    assert review_window("US", datetime.fromisoformat("2026-10-30T15:10:00-04:00"))
    assert review_window("US", datetime.fromisoformat("2026-11-27T12:10:00-05:00"))
    assert review_window("US", datetime.fromisoformat("2026-11-27T15:10:00-05:00")) is None
    assert review_window("US", datetime.fromisoformat("2026-11-28T15:10:00-05:00")) is None
    definition = get_scheduled_task_definition("analysis_us_pre_close_review")
    assert {(s.hour, s.minute) for s in definition.schedules} == {("12,15", "10")}


def test_default_date_does_not_require_completed_today():
    today, previous = default_dates("CN", datetime.fromisoformat("2026-10-30T14:10:00+08:00"))
    assert today.isoformat() == "2026-10-30" and previous.isoformat() == "2026-10-29"


def test_next_run_banner_does_not_advertise_weekend_or_wrong_early_close_time():
    from finance_analysis.holdings_review.calendar import next_review_at

    weekend = datetime.fromisoformat("2026-10-31T10:00:00+08:00")
    assert next_review_at("CN", weekend).isoformat().startswith("2026-11-02T14:10")
    early = datetime.fromisoformat("2026-11-27T10:00:00-05:00")
    assert next_review_at("US", early).isoformat().startswith("2026-11-27T12:10")

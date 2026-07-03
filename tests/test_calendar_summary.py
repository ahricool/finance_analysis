from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from finance_analysis.database.models import CalendarEntry
from finance_analysis.database.repositories.calendar import (
    A_SHARE_CALENDAR_TYPES,
    NEWS_CALENDAR_TYPES,
    US_CALENDAR_TYPES,
    CalendarRepo,
    calendar_category_condition,
)
from finance_analysis.interfaces.api.v1.endpoints import calendar as calendar_endpoint


class _FakeEventRepo:
    def __init__(self, counts):
        self.counts = counts
        self.calls = []

    def count_events_by_date_range(self, start, end):
        self.calls.append((start, end))
        return self.counts


class _FakeCalendarSummaryRepo:
    def __init__(self, counts):
        self.counts = counts
        self.calls = []

    def count_by_date_range(self, start, end, timezone_name="Asia/Shanghai", uid=None):
        self.calls.append(
            {
                "start": start,
                "end": end,
                "timezone_name": timezone_name,
                "uid": uid,
            }
        )
        return self.counts


def test_calendar_summary_returns_range_counts_and_empty_dates(monkeypatch):
    event_repo = _FakeEventRepo({date(2026, 6, 25): 3})
    entry_repo = _FakeCalendarSummaryRepo({date(2026, 6, 25): 1, date(2026, 6, 27): 2})
    monkeypatch.setattr(calendar_endpoint, "_event_repo", lambda: event_repo)
    monkeypatch.setattr(calendar_endpoint, "_repo", lambda: entry_repo)
    monkeypatch.setattr(calendar_endpoint, "get_effective_uid", lambda _request: 7)

    result = calendar_endpoint.get_calendar_summary(
        SimpleNamespace(),
        start_date=date(2026, 6, 25),
        end_date=date(2026, 6, 27),
        timezone="Asia/Shanghai",
    )

    assert result.start_date == "2026-06-25"
    assert result.end_date == "2026-06-27"
    assert [item.model_dump() for item in result.items] == [
        {"date": "2026-06-25", "finance_event_count": 3, "calendar_entry_count": 1},
        {"date": "2026-06-26", "finance_event_count": 0, "calendar_entry_count": 0},
        {"date": "2026-06-27", "finance_event_count": 0, "calendar_entry_count": 2},
    ]


def test_calendar_summary_scopes_calendar_entries_by_uid(monkeypatch):
    event_repo = _FakeEventRepo({})
    entry_repo = _FakeCalendarSummaryRepo({})
    monkeypatch.setattr(calendar_endpoint, "_event_repo", lambda: event_repo)
    monkeypatch.setattr(calendar_endpoint, "_repo", lambda: entry_repo)
    monkeypatch.setattr(calendar_endpoint, "get_effective_uid", lambda _request: 42)

    calendar_endpoint.get_calendar_summary(
        SimpleNamespace(),
        start_date=date(2026, 6, 25),
        end_date=date(2026, 6, 25),
        timezone="America/New_York",
    )

    assert entry_repo.calls == [
        {
            "start": date(2026, 6, 25),
            "end": date(2026, 6, 25),
            "timezone_name": "America/New_York",
            "uid": 42,
        }
    ]


def test_calendar_summary_rejects_ranges_over_31_days(monkeypatch):
    monkeypatch.setattr(calendar_endpoint, "get_effective_uid", lambda _request: 7)

    with pytest.raises(HTTPException) as exc:
        calendar_endpoint.get_calendar_summary(
            SimpleNamespace(),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 7, 2),
            timezone="Asia/Shanghai",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "date_range_too_large"


class _ExecuteRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    def execute(self, stmt):
        del stmt
        return _ExecuteRows(self.rows)


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def get_session(self):
        return _FakeSession(self.rows)


def test_calendar_summary_entry_counts_use_requested_timezone_boundary():
    repo = CalendarRepo(
        db=_FakeDB(
            [
                (datetime(2026, 6, 25, 15, 30, tzinfo=timezone.utc),),
                (datetime(2026, 6, 25, 16, 30, tzinfo=timezone.utc),),
            ]
        )
    )

    shanghai_counts = repo.count_by_date_range(
        date(2026, 6, 25),
        date(2026, 6, 26),
        timezone_name="Asia/Shanghai",
        uid=7,
    )
    new_york_counts = repo.count_by_date_range(
        date(2026, 6, 25),
        date(2026, 6, 26),
        timezone_name="America/New_York",
        uid=7,
    )

    assert shanghai_counts == {date(2026, 6, 25): 1, date(2026, 6, 26): 1}
    assert new_york_counts == {date(2026, 6, 25): 2, date(2026, 6, 26): 0}


def test_calendar_categories_cover_known_market_and_news_types():
    assert A_SHARE_CALENDAR_TYPES == {
        "scheduled_a_share_intraday",
        "a_share_intraday_signal",
        "scheduled_signal_evaluation_cn",
    }
    assert US_CALENDAR_TYPES == {
        "scheduled_us_premarket",
        "scheduled_us_intraday",
        "us_intraday_signal",
        "scheduled_us_postmarket_review",
        "scheduled_signal_evaluation_us",
    }
    assert NEWS_CALENDAR_TYPES == {"scheduled_us_premarket_news"}
    assert "calendar.type IS NULL" in str(calendar_category_condition("other"))


def test_list_calendar_entries_forwards_category_and_pagination(monkeypatch):
    now = datetime(2026, 6, 25, 12, tzinfo=timezone.utc)
    item = CalendarEntry(
        id=7,
        uid=42,
        time=now,
        title="A股盘中分析",
        content="done",
        type="scheduled_a_share_intraday",
        created_at=now,
        updated_at=now,
    )

    class _Repo:
        calls = []

        def list_by_date_paginated(self, day, **kwargs):
            self.calls.append({"day": day, **kwargs})
            return [item], 37

    repo = _Repo()
    monkeypatch.setattr(calendar_endpoint, "_repo", lambda: repo)
    monkeypatch.setattr(calendar_endpoint, "get_effective_uid", lambda _request: 42)

    result = calendar_endpoint.list_calendar_entries(
        SimpleNamespace(),
        query_date=date(2026, 6, 25),
        legacy_time=None,
        timezone="Asia/Shanghai",
        category="a_share",
        page=2,
        limit=20,
    )

    assert result.total == 37
    assert result.page == 2
    assert result.limit == 20
    assert [entry.id for entry in result.items] == [7]
    assert repo.calls == [
        {
            "day": date(2026, 6, 25),
            "timezone_name": "Asia/Shanghai",
            "uid": 42,
            "category": "a_share",
            "page": 2,
            "limit": 20,
        }
    ]

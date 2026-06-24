# -*- coding: utf-8 -*-
"""Tests for market calendar sync task."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from finance_analysis.database.models import FinanceEvent
from finance_analysis.database.repositories.market_calendar_event import FinanceEventUpsertResult
from finance_analysis.tasks.jobs.market_calendar_sync.service import (
    MarketCalendarSyncService,
    is_important_for_notification,
    sort_focus_events,
)


def _finance_event(
    *,
    event_id=1,
    calendar_type="earnings",
    symbol="NVDA",
    event_date=date(2026, 6, 19),
    star=0,
    title="NVDA earnings",
):
    return FinanceEvent(
        id=event_id,
        provider="longbridge",
        event_key=f"key-{event_id}",
        calendar_type=calendar_type,
        market="US",
        symbol=symbol,
        event_date=event_date,
        title=title,
        content=title,
        star=star,
        first_seen_at=datetime(2026, 6, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        last_seen_at=datetime(2026, 6, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        created_at=datetime(2026, 6, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        updated_at=datetime(2026, 6, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


class _FakeRepo:
    def __init__(self):
        self.events = [_finance_event(), _finance_event(event_id=2, calendar_type="dividend", symbol="AAPL")]
        self.marked = []

    def upsert_event(self, event):
        if event["symbol"] == "NVDA":
            return FinanceEventUpsertResult(event=self.events[0], created=True, updated=False)
        return FinanceEventUpsertResult(event=self.events[1], created=False, updated=False)

    def list_events_by_date_range(self, start, end, market=None, calendar_type=None):
        del start, end, market, calendar_type
        return self.events

    def mark_notified(self, event_id, fingerprint, notified_at=None):
        self.marked.append((event_id, fingerprint, notified_at))
        return True


def test_notification_rules_match_required_important_events():
    today = date(2026, 6, 18)

    assert is_important_for_notification(_finance_event(calendar_type="earnings", star=0), [], today) is True
    assert is_important_for_notification(_finance_event(calendar_type="macro", symbol=None, star=0), [], today) is True
    assert is_important_for_notification(_finance_event(calendar_type="split", star=2), [], today) is True
    assert is_important_for_notification(_finance_event(calendar_type="ipo", symbol="AAPL", star=0), ["AAPL"], today) is True
    assert is_important_for_notification(
        _finance_event(calendar_type="dividend", event_date=date(2026, 6, 21), star=0), [], today
    ) is True
    assert is_important_for_notification(
        _finance_event(calendar_type="dividend", event_date=date(2026, 6, 25), star=0), [], today
    ) is False


def test_sort_focus_events_prioritizes_watch_star_type_and_date():
    events = [
        _finance_event(event_id=1, calendar_type="ipo", symbol="ZZZ", event_date=date(2026, 6, 19), star=0),
        _finance_event(event_id=2, calendar_type="dividend", symbol="AAPL", event_date=date(2026, 6, 25), star=0),
        _finance_event(event_id=3, calendar_type="macro", symbol=None, event_date=date(2026, 6, 20), star=3),
    ]

    sorted_events = sort_focus_events(events, ["AAPL"])

    assert [event.id for event in sorted_events] == [2, 3, 1]


def test_sort_focus_events_prioritizes_importance_score_then_watch_list():
    events = [
        _finance_event(event_id=1, calendar_type="earnings", symbol="AAA", star=3),
        _finance_event(event_id=2, calendar_type="earnings", symbol="BBB", star=1),
        _finance_event(event_id=3, calendar_type="earnings", symbol="CCC", star=2),
    ]
    events[0].importance_score = 8
    events[1].importance_score = 10
    events[2].importance_score = 8

    sorted_events = sort_focus_events(events, ["CCC"])

    assert [event.id for event in sorted_events] == [2, 3, 1]


def test_service_continues_when_single_interface_fails_and_records_summary(monkeypatch):
    fetcher = MagicMock()
    fetcher.fetch_earnings_calendar.return_value = [
        {
            "provider": "longbridge",
            "calendar_type": "earnings",
            "market": "US",
            "symbol": "NVDA",
            "event_date": "2026-06-19",
            "title": "NVDA earnings",
            "content_markdown": "content",
        }
    ]
    fetcher.fetch_dividend_calendar.return_value = [
        {
            "provider": "longbridge",
            "calendar_type": "dividend",
            "market": "US",
            "symbol": "AAPL",
            "event_date": "2026-06-20",
            "title": "AAPL dividend",
            "content_markdown": "content",
        }
    ]
    fetcher.fetch_split_calendar.side_effect = RuntimeError("split down")
    fetcher.fetch_ipo_calendar.return_value = []
    fetcher.fetch_macro_calendar.return_value = []
    repo = _FakeRepo()
    calendar_repo = MagicMock()
    calendar_repo.create.return_value = SimpleNamespace(id=9)
    user_repo = MagicMock()
    user_repo.ensure_default_admin.return_value = 1
    notifier = MagicMock()
    notifier.send.return_value = True
    monkeypatch.setattr(
        "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market",
        MagicMock(return_value=["AAPL"]),
    )
    service = MarketCalendarSyncService(
        fetcher=fetcher,
        repo=repo,
        calendar_repo=calendar_repo,
        user_repo=user_repo,
        notifier_factory=lambda: notifier,
    )

    summary = service.run(now=datetime(2026, 6, 18, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

    assert summary.inserted_count == 1
    assert summary.skipped_duplicate_count == 1
    assert any("split" in item for item in summary.errors)
    assert summary.calendar_id == 9
    assert summary.notification_sent_count == 1
    assert summary.importance_candidate_ids == [1]
    assert repo.marked and repo.marked[0][0] == 1
    assert "scheduled_market_calendar" == calendar_repo.create.call_args.kwargs["type"]


def test_importance_candidates_ignore_unrelated_timestamp_changes():
    service = MarketCalendarSyncService(fetcher=MagicMock(), repo=_FakeRepo())
    event = _finance_event()

    assert service._needs_importance_score(
        FinanceEventUpsertResult(event=event, created=False, updated=True, changed_fields=["last_seen_at"])
    ) is False
    assert service._needs_importance_score(
        FinanceEventUpsertResult(event=event, created=False, updated=True, changed_fields=["raw_payload_json"])
    ) is False
    assert service._needs_importance_score(
        FinanceEventUpsertResult(event=event, created=False, updated=True, changed_fields=["data_kv_json"])
    ) is True
    assert service._needs_importance_score(
        FinanceEventUpsertResult(event=event, created=True, updated=False, changed_fields=[])
    ) is True


def test_importance_candidate_ids_are_deduped(monkeypatch):
    fetcher = MagicMock()
    fetcher.fetch_earnings_calendar.return_value = [
        {"provider": "longbridge", "calendar_type": "earnings", "market": "US", "symbol": "NVDA", "event_date": "2026-06-19", "title": "A", "content_markdown": "A"},
        {"provider": "longbridge", "calendar_type": "earnings", "market": "US", "symbol": "NVDA", "event_date": "2026-06-19", "title": "B", "content_markdown": "B"},
    ]
    fetcher.fetch_dividend_calendar.return_value = []
    fetcher.fetch_split_calendar.return_value = []
    fetcher.fetch_ipo_calendar.return_value = []
    fetcher.fetch_macro_calendar.return_value = []
    event = _finance_event(event_id=1)
    repo = MagicMock()
    repo.upsert_event.return_value = FinanceEventUpsertResult(event=event, created=True, updated=False)
    repo.list_events_by_date_range.return_value = []
    monkeypatch.setattr(
        "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market",
        MagicMock(return_value=[]),
    )

    summary = MarketCalendarSyncService(fetcher=fetcher, repo=repo, calendar_repo=MagicMock(), user_repo=MagicMock()).run(
        now=datetime(2026, 6, 18, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert summary.importance_candidate_ids == [1]

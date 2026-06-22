# -*- coding: utf-8 -*-
"""Tests for market calendar event repository helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import HTTPException

from finance_analysis.interfaces.api.v1.endpoints.calendar import list_finance_events
from finance_analysis.database.models import FinanceEvent
from finance_analysis.database.repositories.market_calendar_event import MarketCalendarEventRepo, normalize_event_key


class _ScalarResult:
    def __init__(self, item):
        self.item = item

    def first(self):
        if isinstance(self.item, list):
            return self.item[0] if self.item else None
        return self.item

    def all(self):
        if isinstance(self.item, list):
            return self.item
        return [] if self.item is None else [self.item]


class _ExecuteResult:
    def __init__(self, item):
        self.item = item

    def scalars(self):
        return _ScalarResult(self.item)


class _FakeSession:
    def __init__(self, item=None):
        self.item = item
        self.statement = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    def execute(self, stmt):
        self.statement = stmt
        return _ExecuteResult(self.item)

    def add(self, item):
        self.item = item

    def flush(self):
        if self.item is not None and self.item.id is None:
            self.item.id = 1

    def refresh(self, item):
        pass

    def expunge(self, item):
        pass

    def get(self, model, item_id):
        del model, item_id
        return self.item


class _FakeDB:
    def __init__(self, item=None):
        self.session = _FakeSession(item)

    def get_session(self):
        return self.session

    def _run_write_transaction(self, operation_name, write_operation):
        del operation_name
        return write_operation(self.session)


def _event(**overrides):
    data = {
        "provider": "longbridge",
        "provider_event_id": None,
        "calendar_type": "earnings",
        "market": "US",
        "symbol": "NVDA",
        "event_date": "2026-06-20",
        "event_type": "Release",
        "activity_type": "Earnings",
        "title": "NVDA NVIDIA 财报 Q2 earnings",
        "content": "Q2 earnings",
        "content_markdown": "- 类型：财报",
        "star": 3,
    }
    data.update(overrides)
    return data


def test_normalize_event_key_prefers_provider_event_id():
    first = normalize_event_key(_event(provider_event_id="abc", title="old"))
    second = normalize_event_key(_event(provider_event_id="abc", title="new"))

    assert first == second
    assert first.startswith("longbridge:earnings:id:")


def test_normalize_event_key_fallback_is_stable_for_same_identity():
    first = normalize_event_key(_event())
    second = normalize_event_key(_event())

    assert first == second
    assert first.startswith("fallback:")


def test_upsert_event_inserts_new_event():
    repo = MarketCalendarEventRepo(db=_FakeDB())

    result = repo.upsert_event(_event())

    assert result.created is True
    assert result.updated is False
    assert result.event.id == 1
    assert result.event.symbol == "NVDA"


def test_upsert_event_updates_existing_event_without_duplicate_insert():
    existing = FinanceEvent(
        id=7,
        provider="longbridge",
        event_key=normalize_event_key(_event()),
        calendar_type="earnings",
        market="US",
        symbol="NVDA",
        event_date=date(2026, 6, 20),
        title="Old",
        content="Old",
        first_seen_at=date(2026, 6, 18),
        last_seen_at=date(2026, 6, 18),
        created_at=date(2026, 6, 18),
        updated_at=date(2026, 6, 18),
    )
    repo = MarketCalendarEventRepo(db=_FakeDB(existing))

    result = repo.upsert_event(_event(title="New title", content_markdown="New content"))

    assert result.created is False
    assert result.updated is True
    assert "title" in result.changed_fields
    assert result.event.id == 7
    assert result.event.title == "New title"


def test_list_events_by_date_uses_event_date_filter_and_optional_filters():
    db = _FakeDB([])
    repo = MarketCalendarEventRepo(db=db)

    result = repo.list_events_by_date(date(2026, 6, 20), market="us", calendar_type="earnings")

    assert result == []
    params = db.session.statement.compile().params
    where_text = str(db.session.statement.whereclause)
    assert "finance_events.event_date = :event_date_1" in where_text
    assert params["event_date_1"] == date(2026, 6, 20)
    assert params["market_1"] == "US"
    assert params["calendar_type_1"] == "earnings"


def test_list_events_by_date_sorts_star_desc_then_type_symbol_title():
    rows = [
        FinanceEvent(
            id=1,
            provider="longbridge",
            event_key="event-1",
            calendar_type="macro",
            market="US",
            symbol=None,
            event_date=date(2026, 6, 20),
            title="CPI",
            content="CPI",
            star=None,
            first_seen_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        ),
        FinanceEvent(
            id=2,
            provider="longbridge",
            event_key="event-2",
            calendar_type="earnings",
            market="US",
            symbol="MSFT",
            event_date=date(2026, 6, 20),
            title="Microsoft earnings",
            content="MSFT",
            star=2,
            first_seen_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        ),
        FinanceEvent(
            id=3,
            provider="longbridge",
            event_key="event-3",
            calendar_type="dividend",
            market="US",
            symbol="AAPL",
            event_date=date(2026, 6, 20),
            title="Apple dividend",
            content="AAPL",
            star=2,
            first_seen_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        ),
        FinanceEvent(
            id=4,
            provider="longbridge",
            event_key="event-4",
            calendar_type="earnings",
            market="US",
            symbol="AAPL",
            event_date=date(2026, 6, 20),
            title="Apple earnings",
            content="AAPL",
            star=3,
            first_seen_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        ),
    ]
    repo = MarketCalendarEventRepo(db=_FakeDB(rows))

    result = repo.list_events_by_date(date(2026, 6, 20))

    assert [item.id for item in result] == [4, 3, 2, 1]


def test_list_finance_events_rejects_invalid_timezone():
    try:
        list_finance_events(query_date=date(2026, 6, 20), timezone="UTC")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["error"] == "invalid_timezone"
    else:
        raise AssertionError("expected invalid timezone HTTPException")

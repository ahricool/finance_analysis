# -*- coding: utf-8 -*-
"""Tests for market calendar event repository helpers."""

from __future__ import annotations

from datetime import date

from finance_analysis.database.models import FinanceEvent
from finance_analysis.database.repositories.market_calendar_event import MarketCalendarEventRepo, normalize_event_key


class _ScalarResult:
    def __init__(self, item):
        self.item = item

    def first(self):
        return self.item

    def all(self):
        return [] if self.item is None else [self.item]


class _ExecuteResult:
    def __init__(self, item):
        self.item = item

    def scalars(self):
        return _ScalarResult(self.item)


class _FakeSession:
    def __init__(self, item=None):
        self.item = item

    def execute(self, stmt):
        del stmt
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

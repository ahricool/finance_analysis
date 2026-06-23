# -*- coding: utf-8 -*-
"""Tests for watch list API update field handling."""

from datetime import datetime, timezone
from types import SimpleNamespace

from finance_analysis.interfaces.api.v1.endpoints import watch_list
from finance_analysis.interfaces.api.v1.schemas.watch_list import WatchListItemUpdate


class _FakeRepo:
    def __init__(self):
        self.update_kwargs = None

    def update(self, **kwargs):
        self.update_kwargs = kwargs
        return SimpleNamespace(
            id=kwargs["item_id"],
            uid=kwargs["uid"],
            code="AAPL",
            name="Apple",
            notes=None,
            market_type="US",
            is_favorite=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_update_watch_list_item_clears_explicit_null_notes(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(watch_list, "_repo", lambda: repo)
    monkeypatch.setattr(watch_list, "get_effective_uid", lambda _request: 7)

    body = WatchListItemUpdate(notes=None)

    response = watch_list.update_watch_list_item(SimpleNamespace(), item_id=3, body=body)

    assert response.notes is None
    assert repo.update_kwargs == {
        "item_id": 3,
        "uid": 7,
        "notes": "",
    }

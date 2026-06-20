# -*- coding: utf-8 -*-
"""Tests for watch list repository field handling."""

from finance_analysis.database.repositories.watch_list import WatchListRepo


class _FakeSession:
    def __init__(self, item=None):
        self.item = item

    def add(self, item):
        self.item = item

    def flush(self):
        pass

    def refresh(self, item):
        pass

    def expunge(self, item):
        pass

    def get(self, model, item_id):
        return self.item


class _FakeDB:
    def __init__(self, item=None):
        self.session = _FakeSession(item)

    def _run_write_transaction(self, operation_name, write_operation):
        return write_operation(self.session)


def test_watch_list_create_accepts_market_type_and_favorite_flag():
    repo = WatchListRepo(db=_FakeDB())

    item = repo.create(
        uid=1,
        code=" aapl ",
        name=" Apple ",
        notes=" important ",
        market_type="US",
        is_favorite=True,
    )

    assert item.code == "AAPL"
    assert item.name == "Apple"
    assert item.notes == "important"
    assert item.market_type == "US"
    assert item.is_favorite is True


def test_watch_list_update_accepts_market_type_and_favorite_flag():
    repo = WatchListRepo(db=_FakeDB())
    item = repo.create(uid=1, code="600519", market_type="CN", is_favorite=True)

    updated = WatchListRepo(db=_FakeDB(item)).update(
        item.id or 1,
        uid=1,
        market_type="HK",
        is_favorite=False,
    )

    assert updated is item
    assert updated.market_type == "HK"
    assert updated.is_favorite is False

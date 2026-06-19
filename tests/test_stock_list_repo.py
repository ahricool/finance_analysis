# -*- coding: utf-8 -*-
"""Tests for stock list repository field handling."""

from src.repositories.stock_list_repo import StockListRepo


class _FakeSession:
    def __init__(self, item=None):
        self.item = item

    def add(self, item):
        self.item = item

    def flush(self):
        pass

    def refresh(self, item):
        pass

    def get(self, model, item_id):
        return self.item


class _FakeDB:
    def __init__(self, item=None):
        self.session = _FakeSession(item)

    def _run_write_transaction(self, operation_name, write_operation):
        return write_operation(self.session)


def test_stock_list_create_accepts_market_type_quantity_and_notes():
    repo = StockListRepo(db=_FakeDB())

    item = repo.create(
        uid=1,
        code=" aapl ",
        name=" Apple ",
        quantity=12,
        market_type="US",
        notes=" core ",
    )

    assert item.code == "AAPL"
    assert item.name == "Apple"
    assert item.quantity == 12
    assert item.market_type == "US"
    assert item.notes == "core"


def test_stock_list_update_accepts_market_type_quantity_and_notes():
    repo = StockListRepo(db=_FakeDB())
    item = repo.create(uid=1, code="600519", market_type="CN", quantity=10)

    updated = StockListRepo(db=_FakeDB(item)).update(
        item.id or 1,
        uid=1,
        market_type="HK",
        quantity=0,
        notes=" observe ",
    )

    assert updated is item
    assert updated.market_type == "HK"
    assert updated.quantity == 0
    assert updated.notes == "observe"

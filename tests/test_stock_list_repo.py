# -*- coding: utf-8 -*-
"""Tests for stock list repository field handling."""

from datetime import datetime, timezone
from decimal import Decimal

from finance_analysis.database.models import StockHolding
from finance_analysis.database.repositories.stock_list import StockListRepo


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


def _unique_constraint_columns(model) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }


def test_stock_list_create_accepts_decimal_fields_market_type_and_notes():
    repo = StockListRepo(db=_FakeDB())
    opened_at = datetime(2026, 6, 26, 9, 30, tzinfo=timezone.utc)

    item = repo.create(
        uid=1,
        code=" aapl ",
        name=" Apple ",
        quantity=Decimal("12.345"),
        avg_cost=Decimal("188.1234"),
        opened_at=opened_at,
        market_type="US",
        notes=" core ",
    )

    assert item.code == "AAPL"
    assert item.name == "Apple"
    assert item.quantity == Decimal("12.345")
    assert item.avg_cost == Decimal("188.1234")
    assert item.opened_at == opened_at
    assert item.market_type == "US"
    assert item.notes == "core"


def test_stock_list_update_accepts_decimal_fields_and_notes():
    repo = StockListRepo(db=_FakeDB())
    item = repo.create(uid=1, code="600519", market_type="CN", quantity=10)
    opened_at = datetime(2026, 6, 26, 10, 15, tzinfo=timezone.utc)

    updated = StockListRepo(db=_FakeDB(item)).update(
        item.id or 1,
        uid=1,
        quantity=Decimal("0.5"),
        avg_cost=Decimal("123.4567"),
        opened_at=opened_at,
        notes=" observe ",
    )

    assert updated is item
    assert updated.market_type == "CN"
    assert updated.quantity == Decimal("0.5")
    assert updated.avg_cost == Decimal("123.4567")
    assert updated.opened_at == opened_at
    assert updated.notes == "observe"


def test_stock_list_update_clears_nullable_cost_fields():
    item = StockListRepo(db=_FakeDB()).create(
        uid=1,
        code="AAPL",
        market_type="US",
        quantity=Decimal("1.25"),
        avg_cost=Decimal("100.50"),
        opened_at=datetime(2026, 6, 26, 9, 30, tzinfo=timezone.utc),
    )

    updated = StockListRepo(db=_FakeDB(item)).update(item.id or 1, uid=1, avg_cost=None, opened_at=None)

    assert updated is item
    assert updated.avg_cost is None
    assert updated.opened_at is None


def test_stock_list_unique_identity_includes_market_type():
    assert ("uid", "market_type", "code") in _unique_constraint_columns(StockHolding)

# -*- coding: utf-8 -*-
"""Tests for stock list API field handling."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from finance_analysis.interfaces.api.v1.endpoints import stock_list
from finance_analysis.interfaces.api.v1.schemas.stock_list import StockHoldingCreate, StockHoldingUpdate


class _FakeRepo:
    def __init__(self, existing=None):
        self.existing = existing
        self.get_by_code_args = None
        self.create_kwargs = None
        self.update_kwargs = None

    def get_by_code(self, code, uid=None, market_type=None):
        self.get_by_code_args = {"code": code, "uid": uid, "market_type": market_type}
        return self.existing

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return SimpleNamespace(
            id=9,
            uid=kwargs["uid"],
            code=kwargs["code"],
            name=kwargs["name"],
            quantity=kwargs["quantity"],
            avg_cost=kwargs["avg_cost"],
            opened_at=kwargs["opened_at"],
            market_type=kwargs["market_type"],
            notes=kwargs["notes"],
            created_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 26, 1, tzinfo=timezone.utc),
        )

    def update(self, item_id, **kwargs):
        self.update_kwargs = {"item_id": item_id, **kwargs}
        return SimpleNamespace(
            id=item_id,
            uid=kwargs["uid"],
            code="AAPL",
            name=kwargs.get("name") or "Apple",
            quantity=kwargs.get("quantity", Decimal("1.25")),
            avg_cost=kwargs.get("avg_cost"),
            opened_at=kwargs.get("opened_at"),
            market_type="US",
            notes=kwargs.get("notes"),
            created_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 26, 1, tzinfo=timezone.utc),
        )


class _MarketScopedExistingRepo(_FakeRepo):
    def get_by_code(self, code, uid=None, market_type=None):
        self.get_by_code_args = {"code": code, "uid": uid, "market_type": market_type}
        return object() if market_type == "HK" else None


def test_create_stock_holding_accepts_decimal_fields_and_serializes_json(monkeypatch):
    opened_at = datetime(2026, 6, 26, 9, 30, tzinfo=timezone.utc)
    repo = _FakeRepo()
    monkeypatch.setattr(stock_list, "_repo", lambda: repo)
    monkeypatch.setattr(stock_list, "get_effective_uid", lambda _request: 7)

    response = stock_list.create_stock_holding(
        SimpleNamespace(),
        StockHoldingCreate(
            code="aapl",
            name="Apple",
            market_type="US",
            quantity=Decimal("1.2345"),
            avg_cost=Decimal("188.1200"),
            opened_at=opened_at,
            notes="core",
        ),
    )

    assert repo.get_by_code_args == {"code": "AAPL", "uid": 7, "market_type": "US"}
    assert repo.create_kwargs["quantity"] == Decimal("1.2345")
    assert repo.create_kwargs["avg_cost"] == Decimal("188.1200")
    assert repo.create_kwargs["opened_at"] == opened_at
    assert response.model_dump(mode="json")["quantity"] == "1.2345"
    assert response.model_dump(mode="json")["avg_cost"] == "188.1200"


def test_create_stock_holding_duplicate_check_is_market_scoped(monkeypatch):
    repo = _FakeRepo(existing=object())
    monkeypatch.setattr(stock_list, "_repo", lambda: repo)
    monkeypatch.setattr(stock_list, "get_effective_uid", lambda _request: 7)

    with pytest.raises(HTTPException) as exc_info:
        stock_list.create_stock_holding(
            SimpleNamespace(),
            StockHoldingCreate(code="00700", market_type="HK", quantity=Decimal("1")),
        )

    assert exc_info.value.status_code == 409
    assert repo.get_by_code_args == {"code": "00700", "uid": 7, "market_type": "HK"}


def test_create_stock_holding_allows_same_code_in_different_market(monkeypatch):
    repo = _MarketScopedExistingRepo()
    monkeypatch.setattr(stock_list, "_repo", lambda: repo)
    monkeypatch.setattr(stock_list, "get_effective_uid", lambda _request: 7)

    response = stock_list.create_stock_holding(
        SimpleNamespace(),
        StockHoldingCreate(code="00700", market_type="US", quantity=Decimal("2")),
    )

    assert response.code == "00700"
    assert response.market_type == "US"
    assert repo.get_by_code_args == {"code": "00700", "uid": 7, "market_type": "US"}


def test_update_stock_holding_can_clear_nullable_decimal_and_datetime(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(stock_list, "_repo", lambda: repo)
    monkeypatch.setattr(stock_list, "get_effective_uid", lambda _request: 7)

    response = stock_list.update_stock_holding(
        SimpleNamespace(),
        item_id=3,
        body=StockHoldingUpdate(avg_cost=None, opened_at=None),
    )

    assert repo.update_kwargs == {
        "item_id": 3,
        "uid": 7,
        "avg_cost": None,
        "opened_at": None,
    }
    assert response.avg_cost is None
    assert response.opened_at is None


def test_stock_holding_schema_rejects_float_decimal_values():
    with pytest.raises(ValidationError):
        StockHoldingCreate(code="AAPL", market_type="US", avg_cost=188.12)

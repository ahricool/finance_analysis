# -*- coding: utf-8 -*-
"""Tests for watch list API update field handling."""

from datetime import datetime, timezone
from types import SimpleNamespace

from finance_analysis.interfaces.api.v1.endpoints import watch_list
from finance_analysis.interfaces.api.v1.schemas.watch_list import WatchListItemCreate, WatchListItemUpdate


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
            id=5,
            uid=kwargs["uid"],
            code=kwargs["code"],
            name=kwargs["name"],
            notes=kwargs["notes"],
            market_type=kwargs["market_type"],
            is_favorite=kwargs["is_favorite"],
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

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


class _MarketScopedExistingRepo(_FakeRepo):
    def get_by_code(self, code, uid=None, market_type=None):
        self.get_by_code_args = {"code": code, "uid": uid, "market_type": market_type}
        return object() if market_type == "HK" else None


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


def test_create_watch_list_item_duplicate_check_is_market_scoped(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(watch_list, "_repo", lambda: repo)
    monkeypatch.setattr(watch_list, "get_effective_uid", lambda _request: 7)

    response = watch_list.create_watch_list_item(
        SimpleNamespace(),
        WatchListItemCreate(code="aapl", name="Apple", market_type="US"),
    )

    assert response.code == "AAPL"
    assert repo.get_by_code_args == {"code": "AAPL", "uid": 7, "market_type": "US"}
    assert repo.create_kwargs["market_type"] == "US"


def test_create_watch_list_item_allows_same_code_in_different_market(monkeypatch):
    repo = _MarketScopedExistingRepo()
    monkeypatch.setattr(watch_list, "_repo", lambda: repo)
    monkeypatch.setattr(watch_list, "get_effective_uid", lambda _request: 7)

    response = watch_list.create_watch_list_item(
        SimpleNamespace(),
        WatchListItemCreate(code="00700", name="Ticker", market_type="US"),
    )

    assert response.code == "00700"
    assert response.market_type == "US"
    assert repo.get_by_code_args == {"code": "00700", "uid": 7, "market_type": "US"}


def test_create_rejects_default_market_conflict_before_any_write_or_name_lookup(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import Mock

    repo = _FakeRepo()
    market = Mock()
    monkeypatch.setattr(watch_list, "_repo", lambda: repo)
    monkeypatch.setattr(watch_list, "get_effective_uid", lambda _request: 7)
    monkeypatch.setattr(watch_list, "MarketDataService", market)
    app = FastAPI()
    app.include_router(watch_list.router, prefix="/watch-list")
    with TestClient(app) as client:
        response = client.post("/watch-list", json={"code": "AAPL.US", "name": "Apple"})
    assert response.status_code == 422
    assert repo.create_kwargs is None and repo.get_by_code_args is None
    market.assert_not_called()


def test_legacy_invalid_row_stays_visible_without_breaking_list_response():
    repo = _FakeRepo()
    rows = [repo.create(uid=7, code=code, name=None, notes=None, market_type=market, is_favorite=False)
            for code, market in [("AAPL.US", "CN"), ("MSFT", "US")]]
    result = watch_list._responses(repo, rows)
    assert result[0].code == "AAPL.US" and result[0].market_type == "CN"
    assert result[0].validation_error
    assert result[1].code == "MSFT" and result[1].validation_error is None


def test_update_validation_error_is_422(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from unittest.mock import Mock

    repo = _FakeRepo()
    repo.update = Mock(side_effect=ValueError("code/market conflict"))
    monkeypatch.setattr(watch_list, "_repo", lambda: repo)
    monkeypatch.setattr(watch_list, "get_effective_uid", lambda _request: 7)
    with pytest.raises(HTTPException) as error:
        watch_list.update_watch_list_item(SimpleNamespace(), 3, WatchListItemUpdate(market_type="CN"))
    assert error.value.status_code == 422

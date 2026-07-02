from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.signal import Signal
from finance_analysis.database.repositories.signal import SignalRepository
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.middlewares.error_handler import add_error_handlers
from finance_analysis.interfaces.api.v1.endpoints import signals

UTC = timezone.utc


class _Database:
    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Signal.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    @contextmanager
    def get_session(self):
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()


def _create_signal(
    repository: SignalRepository,
    *,
    code: str,
    market: str,
    direction: str,
    signal_type: str,
    signal_at: datetime,
) -> Signal:
    return repository.create(
        code=code,
        name=f"{code} name",
        market=market,
        direction=direction,
        signal_type=signal_type,
        signal_version="v2",
        price=100,
        signal_at=signal_at,
        evaluation={},
    )


def test_signal_repository_filters_sorts_and_paginates_without_related_queries():
    repository = SignalRepository(_Database())
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    _create_signal(
        repository,
        code="NVDA",
        market="US",
        direction="bullish",
        signal_type="relative_strength_breakout",
        signal_at=now,
    )
    _create_signal(
        repository,
        code="AAPL",
        market="US",
        direction="bearish",
        signal_type="strong_to_weak_failure",
        signal_at=now - timedelta(hours=1),
    )
    _create_signal(
        repository,
        code="300502",
        market="CN",
        direction="sideways",
        signal_type="weak_to_strong_reversal",
        signal_at=now - timedelta(days=2),
    )

    rows = repository.list_signals(limit=2, offset=0)
    assert [row.code for row in rows] == ["NVDA", "AAPL"]
    assert repository.count_signals() == 3

    assert [
        row.code
        for row in repository.list_signals(limit=20, offset=0, market="CN")
    ] == ["300502"]
    assert [
        row.code
        for row in repository.list_signals(limit=20, offset=0, direction="bearish")
    ] == ["AAPL"]
    assert [
        row.code
        for row in repository.list_signals(
            limit=20,
            offset=0,
            signal_type="relative_strength_breakout",
        )
    ] == ["NVDA"]
    assert [
        row.code
        for row in repository.list_signals(limit=20, offset=0, keyword="vd")
    ] == ["NVDA"]
    assert [
        row.code
        for row in repository.list_signals(
            limit=20,
            offset=0,
            signal_at_from=now - timedelta(hours=2),
            signal_at_to=now - timedelta(minutes=30),
        )
    ] == ["AAPL"]
    assert [
        row.code
        for row in repository.list_signals(limit=1, offset=1)
    ] == ["AAPL"]


class _FakeRepository:
    def __init__(self, items):
        self.items = items
        self.list_kwargs = None
        self.count_kwargs = None

    def list_signals(self, **kwargs):
        self.list_kwargs = kwargs
        return self.items

    def count_signals(self, **kwargs):
        self.count_kwargs = kwargs
        return len(self.items)

    def get_by_id(self, signal_id):
        return next((item for item in self.items if item.id == signal_id), None)


def _signal_payload(signal_id=1):
    now = datetime(2026, 6, 30, 14, 34, tzinfo=UTC)
    return SimpleNamespace(
        id=signal_id,
        market="US",
        code="NVDA",
        name=None,
        signal_type="relative_strength_breakout",
        signal_version="v2",
        direction="bullish",
        signal_at=now,
        price=158.2,
        evaluation={
            "30m": {
                "price": 159.1,
                "return_pct": 0.5689,
                "max_return_pct": 0.92,
                "min_return_pct": -0.21,
                "evaluated_at": "2026-06-30T15:04:00Z",
            }
        },
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def signal_client(monkeypatch):
    repository = _FakeRepository([_signal_payload()])
    monkeypatch.setattr(signals, "_repo", lambda: repository)
    app = FastAPI()
    app.include_router(signals.router, prefix="/api/v1/signals")
    add_error_handlers(app)
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1, role="user")
    return TestClient(app), repository


def test_signal_list_api_maps_filters_and_returns_paginated_response(signal_client):
    client, repository = signal_client
    response = client.get(
        "/api/v1/signals",
        params={
            "page": 2,
            "page_size": 20,
            "market": "US",
            "direction": "bullish",
            "signal_type": "relative_strength_breakout",
            "keyword": "NVDA",
            "signal_at_from": "2026-06-30T00:00:00Z",
            "signal_at_to": "2026-06-30T23:59:59Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 2
    assert payload["page_size"] == 20
    assert payload["items"][0]["signal_price"] == 158.2
    assert payload["items"][0]["evaluation"]["30m"]["return_pct"] == 0.5689
    assert repository.list_kwargs["limit"] == 20
    assert repository.list_kwargs["offset"] == 20
    assert repository.list_kwargs["market"] == "US"
    assert repository.list_kwargs["direction"] == "bullish"
    assert repository.count_kwargs == {
        key: value
        for key, value in repository.list_kwargs.items()
        if key not in {"limit", "offset"}
    }


def test_signal_list_api_rejects_invalid_direction(signal_client):
    client, _ = signal_client
    response = client.get("/api/v1/signals", params={"direction": "up"})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_signal_list_api_rejects_naive_date_range(signal_client):
    client, _ = signal_client
    response = client.get(
        "/api/v1/signals",
        params={"signal_at_from": "2026-06-30T00:00:00"},
    )
    assert response.status_code == 422


def test_signal_detail_api_returns_item_and_404(signal_client):
    client, _ = signal_client
    response = client.get("/api/v1/signals/1")
    assert response.status_code == 200
    assert response.json()["id"] == 1
    assert response.json()["direction"] == "bullish"

    missing = client.get("/api/v1/signals/999")
    assert missing.status_code == 404

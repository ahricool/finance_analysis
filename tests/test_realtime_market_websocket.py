from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
from finance_analysis.interfaces.api.app import create_app
from finance_analysis.interfaces.api.v1.endpoints import market_data
from finance_analysis.users.auth import COOKIE_NAME


class FakeQuoteRepository:
    def __init__(self, quotes: dict[str, QuoteState]) -> None:
        self.quotes = quotes
        self.requested: list[str] = []
        self.closed = False

    async def get_quotes(self, symbols):
        self.requested = list(symbols)
        return {symbol: self.quotes[symbol] for symbol in self.requested if symbol in self.quotes}

    async def close(self) -> None:
        self.closed = True


def quote(symbol: str, last_price: str, pre_close: str) -> QuoteState:
    now = datetime(2026, 6, 30, 2, 30, tzinfo=timezone.utc)
    value = QuoteState(symbol=symbol)
    value.merge(
        {
            "last_price": Decimal(last_price),
            "pre_close": Decimal(pre_close),
            "open": Decimal("100"),
            "high": Decimal("103"),
            "low": Decimal("99"),
            "volume": 1234,
        },
        event_time=now,
        received_at=now,
    )
    return value


@pytest.mark.asyncio
async def test_snapshot_calculates_change_and_keeps_missing_quotes(monkeypatch) -> None:
    stocks = [
        market_data.TrackedStock("AAPL", "US", "AAPL.US"),
        market_data.TrackedStock("00700", "HK", "0700.HK"),
    ]
    repository = FakeQuoteRepository({"AAPL.US": quote("AAPL.US", "102", "100")})
    monkeypatch.setattr(market_data, "_load_tracked_stocks", lambda uid: stocks)

    snapshot = await market_data._build_snapshot(7, repository)

    assert repository.requested == ["AAPL.US", "0700.HK"]
    assert snapshot["quotes"][0]["change_amount"] == 2.0
    assert snapshot["quotes"][0]["change_pct"] == 2.0
    assert snapshot["quotes"][1] == {
        "code": "00700",
        "market_type": "HK",
        "symbol": "0700.HK",
        "available": False,
    }


def test_websocket_requires_session(monkeypatch) -> None:
    monkeypatch.setattr(market_data, "parse_session_uid", lambda value: None)
    client = TestClient(create_app())

    with pytest.raises(Exception) as caught:
        with client.websocket_connect("/api/v1/market-data/ws") as websocket:
            websocket.receive_json()

    assert getattr(caught.value, "code", None) == 4401


def test_websocket_sends_user_scoped_redis_snapshot_and_closes_repository(monkeypatch) -> None:
    repository = FakeQuoteRepository({"AAPL.US": quote("AAPL.US", "99", "100")})
    stocks = [market_data.TrackedStock("AAPL", "US", "AAPL.US")]
    monkeypatch.setattr(market_data, "parse_session_uid", lambda value: 7)
    monkeypatch.setattr(
        market_data,
        "UserRepository",
        lambda: SimpleNamespace(get_by_uid=lambda uid: SimpleNamespace(id=uid)),
    )
    monkeypatch.setattr(market_data, "_load_tracked_stocks", lambda uid: stocks)
    monkeypatch.setattr(market_data.RealtimeStateRepository, "from_url", lambda url: repository)
    client = TestClient(create_app())
    client.cookies.set(COOKIE_NAME, "valid-session")

    with client.websocket_connect("/api/v1/market-data/ws") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "quotes"
        assert message["quotes"][0]["change_amount"] == -1.0

    assert repository.requested == ["AAPL.US"]
    assert repository.closed is True

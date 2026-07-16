from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from finance_analysis.integrations.market_data.realtime_state.models import QuoteState, TrendState
from finance_analysis.interfaces.api.app import create_app
from finance_analysis.interfaces.api.v1.endpoints import market_data
from finance_analysis.users.auth import COOKIE_NAME


class FakeQuoteRepository:
    def __init__(self, quotes: dict[str, QuoteState], trends: dict[str, TrendState] | None = None) -> None:
        self.quotes = quotes
        self.trends = trends or {}
        self.requested: list[str] = []
        self.trend_requested: list[str] = []
        self.closed = False

    async def get_quotes(self, symbols):
        self.requested = list(symbols)
        return {symbol: self.quotes[symbol] for symbol in self.requested if symbol in self.quotes}

    async def get_trend_states(self, symbols):
        self.trend_requested = list(symbols)
        return {symbol: self.trends[symbol] for symbol in self.trend_requested if symbol in self.trends}

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


def test_tracked_stocks_deduplicate_watchlist_and_holdings_by_symbol(monkeypatch) -> None:
    item = SimpleNamespace(code="aapl", market_type="us")
    monkeypatch.setattr(market_data, "WatchListRepo", lambda: SimpleNamespace(list_all=lambda uid: [item]))
    monkeypatch.setattr(market_data, "StockListRepo", lambda: SimpleNamespace(list_all=lambda uid: [item]))

    stocks = market_data._load_tracked_stocks(7)

    assert stocks == [market_data.TrackedStock("AAPL", "US", "AAPL.US")]


@pytest.mark.asyncio
async def test_snapshot_calculates_change_and_keeps_missing_quotes(monkeypatch) -> None:
    stocks = [
        market_data.TrackedStock("AAPL", "US", "AAPL.US"),
        market_data.TrackedStock("00700", "HK", "0700.HK"),
    ]
    repository = FakeQuoteRepository({"AAPL.US": quote("AAPL.US", "102", "100")})
    monkeypatch.setattr(market_data, "_load_tracked_stocks", lambda uid: stocks)
    monkeypatch.setattr(market_data, "utc_now", lambda: datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc))

    snapshot = await market_data._build_snapshot(7, repository)

    assert repository.requested == ["AAPL.US", "0700.HK"]
    assert repository.trend_requested == ["AAPL.US", "0700.HK"]
    assert snapshot["quotes"][0]["change_amount"] == 2.0
    assert snapshot["quotes"][0]["change_pct"] == 2.0
    assert snapshot["quotes"][1]["available"] is False
    assert snapshot["quotes"][1]["trend_1m"]["state"] == "insufficient"


@pytest.mark.asyncio
async def test_snapshot_serializes_current_trend_and_expires_previous_session(monkeypatch) -> None:
    now = datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc)
    current = TrendState(
        symbol="AAPL.US",
        effective_period=8,
        state="above",
        streak=2,
        ma_value=Decimal("132.48"),
        close=Decimal("132.96"),
        distance_pct=Decimal("0.36"),
        bar_time=datetime(2026, 7, 16, 14, 31, tzinfo=timezone.utc),
        trading_date=date(2026, 7, 16),
        trade_session="Intraday",
        confirmed=True,
    )
    stale = replace(current, symbol="TSLA.US", trading_date=date(2026, 7, 15))
    stocks = [
        market_data.TrackedStock("AAPL", "US", "AAPL.US"),
        market_data.TrackedStock("TSLA", "US", "TSLA.US"),
    ]
    repository = FakeQuoteRepository({}, {"AAPL.US": current, "TSLA.US": stale})
    monkeypatch.setattr(market_data, "_load_tracked_stocks", lambda uid: stocks)
    monkeypatch.setattr(market_data, "utc_now", lambda: now)

    snapshot = await market_data._build_snapshot(7, repository)

    assert snapshot["quotes"][0]["trend_1m"]["ma_value"] == 132.48
    assert snapshot["quotes"][0]["trend_1m"]["confirmed"] is True
    assert snapshot["quotes"][1]["trend_1m"]["state"] == "insufficient"
    assert snapshot["quotes"][1]["available"] is False


@pytest.mark.asyncio
async def test_trend_read_failure_does_not_hide_quote(monkeypatch) -> None:
    repository = FakeQuoteRepository({"AAPL.US": quote("AAPL.US", "102", "100")})

    async def fail(symbols):
        raise RuntimeError("trend redis unavailable")

    repository.get_trend_states = fail
    monkeypatch.setattr(
        market_data,
        "_load_tracked_stocks",
        lambda uid: [market_data.TrackedStock("AAPL", "US", "AAPL.US")],
    )
    monkeypatch.setattr(market_data, "utc_now", lambda: datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc))

    snapshot = await market_data._build_snapshot(7, repository)

    assert snapshot["quotes"][0]["available"] is True
    assert snapshot["quotes"][0]["last_price"] == 102.0
    assert snapshot["quotes"][0]["trend_1m"]["state"] == "insufficient"


@pytest.mark.asyncio
async def test_weekend_keeps_latest_completed_trading_session(monkeypatch) -> None:
    friday = date(2026, 7, 17)
    current = TrendState(
        symbol="AAPL.US",
        effective_period=20,
        state="above",
        streak=5,
        ma_value=Decimal("100"),
        close=Decimal("101"),
        bar_time=datetime(2026, 7, 17, 19, 59, tzinfo=timezone.utc),
        trading_date=friday,
        trade_session="Intraday",
        confirmed=True,
    )
    repository = FakeQuoteRepository({}, {"AAPL.US": current})
    monkeypatch.setattr(
        market_data,
        "_load_tracked_stocks",
        lambda uid: [market_data.TrackedStock("AAPL", "US", "AAPL.US")],
    )
    monkeypatch.setattr(
        market_data, "utc_now", lambda: datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc)
    )

    snapshot = await market_data._build_snapshot(7, repository)

    assert snapshot["quotes"][0]["trend_1m"]["state"] == "above"
    assert snapshot["quotes"][0]["trend_1m"]["trading_date"] == friday.isoformat()


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

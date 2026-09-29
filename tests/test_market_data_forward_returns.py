"""Offline research-return contracts, including holidays and exact-date gaps."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.integrations.market_data.forward_returns import forward_returns
from finance_analysis.interfaces.api.v1.endpoints import market_data


def bar(day, close=100, volume=100):
    return SimpleNamespace(trade_date=date.fromisoformat(day), close=close, volume=volume)


def service_with(*bars):
    service = Mock()
    service.get_daily_bars.return_value = SimpleNamespace(data={"AAPL.US": bars})
    return service


def test_batched_exact_sessions_no_shift_and_no_future_intraday_prices():
    service = service_with(bar("2026-09-18"), bar("2026-09-23", 110),
                           bar("2026-09-24", 120), bar("2026-10-02", 90))
    result = forward_returns(service, ["AAPL.US", "MSFT.US"], "US", date(2026, 9, 18),
                             now=datetime(2026, 10, 2, 19, tzinfo=timezone.utc))
    row = result["items"][0]
    assert row["forward_return_3d"] == pytest.approx(.1)
    assert row["forward_return_5d"] is None  # Sep 25 is missing; do not use Sep 24.
    assert row["forward_return_10d"] is None  # Oct 2 has not closed.
    assert all(value is None for key, value in result["items"][1].items() if key != "code")
    service.get_daily_bars.assert_called_once_with(
        ["AAPL.US", "MSFT.US"], date(2026, 9, 18), date(2026, 9, 25),
        adjustment="forward", source_policy="db_only",
    )
    row = forward_returns(service, ["AAPL.US"], "US", date(2026, 9, 18),
                          now=datetime(2026, 10, 3, tzinfo=timezone.utc))["items"][0]
    assert row["forward_return_10d"] == pytest.approx(-.1)


@pytest.mark.parametrize("base", [None, bar("2026-09-18", 0), bar("2026-09-18", float("nan")),
                                  bar("2026-09-18", 100, 0)])
def test_invalid_or_missing_baseline(base):
    service = service_with(*([base] if base else []), bar("2026-09-23", 110))
    row = forward_returns(service, ["AAPL.US"], "US", date(2026, 9, 18),
                          now=datetime(2026, 10, 3, tzinfo=timezone.utc))["items"][0]
    assert all(value is None for key, value in row.items() if key != "code")


def test_cn_holidays_and_pending_skip_database():
    service = Mock()
    service.get_daily_bars.return_value = SimpleNamespace(data={
        "600000.SH": [bar("2025-09-30"), bar("2025-10-13", 120)],
    })
    row = forward_returns(service, ["600000.SH"], "CN", date(2025, 9, 30),
                          now=datetime(2025, 10, 13, 8, tzinfo=timezone.utc))["items"][0]
    assert row["forward_return_3d"] == pytest.approx(.2)
    assert row["forward_return_5d"] is None
    service.reset_mock()
    forward_returns(service, ["600000.SH"], "CN", date(2025, 9, 30),
                    now=datetime(2025, 10, 1, tzinfo=timezone.utc))
    service.get_daily_bars.assert_not_called()


def test_api_schema_market_validation_and_errors(monkeypatch):
    app = FastAPI()
    app.include_router(market_data.router)
    client = TestClient(app)
    service = service_with()
    monkeypatch.setattr(market_data, "MarketDataService", lambda: service)
    payload = {"market": "US", "trade_date": "2025-09-18", "symbols": ["AAPL", "AAPL.US"]}
    response = client.post('/forward-returns', json=payload)
    assert response.status_code == 200
    assert response.json()["items"] == [{"code": "AAPL.US", "forward_return_3d": None,
                                         "forward_return_5d": None, "forward_return_10d": None}]
    assert client.post('/forward-returns', json={**payload, "market": "CN"}).status_code == 422
    assert client.post('/forward-returns', json={**payload, "symbols": []}).status_code == 422
    service.get_daily_bars.side_effect = RuntimeError("private database error")
    response = client.post('/forward-returns', json=payload)
    assert response.status_code == 503
    assert "private database error" not in response.text

"""Display valuation, daily trade attribution and user isolation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from finance_analysis.portfolio import valuation
from tests.portfolio.test_service import _service

NOW = datetime(2026, 7, 16, 2, 40, tzinfo=timezone.utc)


def quote(**changes):
    return SimpleNamespace(**dict(price=13, pre_close=10, quote_time=NOW, provider="fuyao") | changes)


def test_summary_batches_quotes_names_and_includes_intraday_buy_sell_pnl(monkeypatch):
    service = _service()
    account = next(a for a in service.ensure_accounts(3) if a["market"] == "CN")
    first = service.buy(
        3, account_id=account["id"], symbol="600519.SH", quantity=100, price=10, executed_at=NOW - timedelta(days=1)
    )
    service.sell(3, position_id=first["id"], quantity=20, price=12, executed_at=NOW - timedelta(minutes=20))
    service.buy(
        3, account_id=account["id"], symbol="600519.SH", quantity=10, price=11, executed_at=NOW - timedelta(minutes=10)
    )
    calls = []

    def quotes(symbols):
        calls.append(symbols)
        return SimpleNamespace(data={"600519.SH": quote()})

    monkeypatch.setattr(valuation, "utc_now", lambda: NOW)
    result = valuation.portfolio_summary(
        3, "CN", service=service, market_data=SimpleNamespace(get_realtime_quotes=quotes)
    )
    row = result["positions"][0]
    assert calls == [["600519.SH"]]
    assert row["name"]
    assert row["current_price"] == "13"
    assert Decimal(row["day_pnl"]) == 300  # 90*(13-10) +20*(12-10) -10*(11-10)
    assert row["change_pct"] == "30.0"
    assert row["quote_status"] == "current"
    assert result["missing_quote_count"] == 0
    other = valuation.portfolio_summary(
        4, "CN", service=service, market_data=SimpleNamespace(get_realtime_quotes=quotes)
    )
    assert other["positions"] == []
    assert len(calls) == 1


@pytest.mark.parametrize(
    "as_of,status",
    [(NOW - timedelta(minutes=15), "delayed"), (None, "unavailable"), (NOW + timedelta(minutes=1), "unavailable")],
)
def test_display_retains_delayed_price_but_never_invents_quote_time(as_of, status):
    item = {"market": "CN", "quantity": Decimal(100), "average_cost": Decimal(10)}
    result = valuation.position_valuation(item, quote(quote_time=as_of), [], now=NOW)
    assert result["quote_status"] == status
    assert (result["current_price"] is not None) == (status == "delayed")
    assert (result["day_pnl"] is not None) == (status == "delayed")


def test_missing_previous_close_only_disables_daily_metrics():
    item = {"market": "CN", "quantity": Decimal(100), "average_cost": Decimal(10)}
    result = valuation.position_valuation(item, quote(pre_close=None), [], now=NOW)
    assert result["day_pnl"] is None
    assert result["change_pct"] is None
    assert Decimal(result["unrealized_pnl"]) == 300
    assert Decimal(result["unrealized_pnl_pct"]) == 30


def test_live_snapshot_does_not_initialize_accounts_or_call_market_for_empty_portfolio(monkeypatch):
    service = _service()
    monkeypatch.setattr(service, "ensure_accounts", lambda uid: pytest.fail("stream must be read-only"))
    result = valuation.portfolio_summary(
        7,
        "US",
        service=service,
        initialize_accounts=False,
        market_data=SimpleNamespace(get_realtime_quotes=lambda symbols: pytest.fail("empty portfolio")),
    )
    assert result["accounts"] == result["positions"] == []
    assert result["cash"] == "0"


def test_slow_quote_fetch_keeps_fact_snapshot_time_for_client_ordering(monkeypatch):
    service = _service()
    account = next(a for a in service.ensure_accounts(3) if a["market"] == "CN")
    service.buy(
        3, account_id=account["id"], symbol="600519.SH", quantity=1, price=10, executed_at=NOW - timedelta(days=1)
    )
    times = iter([NOW, NOW + timedelta(seconds=15)])
    monkeypatch.setattr(valuation, "utc_now", lambda: next(times))
    result = valuation.portfolio_summary(
        3,
        "CN",
        service=service,
        market_data=SimpleNamespace(
            get_realtime_quotes=lambda symbols: SimpleNamespace(data={"600519.SH": quote()}),
        ),
    )
    assert result["generated_at"] == valuation.utc_isoformat(NOW)

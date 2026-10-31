"""Snapshot dates, compact fields and minute aggregation are enforced before the model."""

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from finance_analysis.holdings_review.context import ReviewContextBuilder, minute_rows
from finance_analysis.integrations.market_data.models import MarketBar
from finance_analysis.integrations.market_data.models import Market

NOW = datetime.fromisoformat("2026-10-30T14:10:00+08:00")


def bar(when):
    return MarketBar(
        symbol="600519.SH",
        market=Market.CN,
        provider="test",
        bar_time=when,
        trade_date=when.date(),
        interval="1m",
        amount=10000,
        currency="CNY",
        adjustment="forward",
        open=100,
        high=102,
        low=99,
        close=101,
        volume=100,
    )


def test_closed_minute_aggregation_rejects_future_and_old_days():
    bars = [bar(NOW - timedelta(minutes=n)) for n in range(1, 81)]
    bars += [bar(NOW), bar(NOW + timedelta(minutes=1)), bar(NOW - timedelta(days=1))]
    rows = minute_rows(bars, "CN", NOW)
    assert len(rows) == 12
    assert rows[-1][0].startswith("2026-10-30T06:05")
    assert rows[-1][5] == 500


class Previews:
    def __init__(self, status="fresh"):
        self.status, self.calls = status, []

    def read(self, namespace, market, variant, **kwargs):
        self.calls.append((namespace, kwargs))
        when = NOW - timedelta(minutes=10 if self.status == "fresh" else 40)
        payload = {"status": "completed", "trade_date": NOW.date().isoformat(), "preview_time": when.isoformat()}
        row = {
            "code": "600519.SH",
            "name": "茅台",
            "state": "TRENDING",
            "alpha_score": 80,
            "composite_score": 70,
            "debug": "DO_NOT_SEND",
            "features": {"raw": "large"},
        }
        if namespace == "industry_strength":
            payload = {"status": "completed", "result": {"generated_at": when.isoformat()}}
        header = {"trade_date": NOW.date().isoformat()}
        if namespace == "trend_following":
            header.update(payload)
        else:
            header["payload"] = payload
        return {"header": header, "shared": {}, "items": [{"summary": row}], "observed_at": when.isoformat()}


@pytest.mark.parametrize("fresh", [True, False])
def test_preview_whitelist_and_expiry(fresh):
    previews = Previews("fresh" if fresh else "old")
    builder = ReviewContextBuilder(market_data=NS(), resolver=NS(), previews=previews, instruments=NS())
    result = builder._preview("trend_following", "CN", NOW, keys=["600519.SH"], limit=None, variant=20)
    assert result["status"] == ("available" if fresh else "stale_or_unverified")
    assert previews.calls[0][1]["item_keys"] == ["600519.SH"]
    if fresh:
        assert result["items"] == [{"code": "600519.SH", "state": "TRENDING", "alpha_score": 80}]
    else:
        assert not result["items"]


def test_real_portfolio_input_is_compact_and_does_not_include_today_history():
    position = NS(
        position_id="11",
        account_id="1",
        symbol="600519.SH",
        name=None,
        quantity=Decimal("100"),
        average_cost=Decimal("90"),
        lots=[],
    )
    portfolio = NS(valuation_positions=lambda market: [position], db_cash=lambda market: Decimal("10000"))
    history = [bar(NOW - timedelta(days=n)) for n in range(0, 31)]

    class Data:
        def get_realtime_quotes(self, symbols):
            return NS(data={"600519.SH": NS(price=101, quote_time=NOW, change_pct=1)})

        def get_daily_bars(self, *args, **kwargs):
            assert kwargs["adjustment"] == "forward"
            return NS(data={"600519.SH": history})

        def get_minute_bars(self, *args, **kwargs):
            return NS(data={"600519.SH": [bar(NOW - timedelta(minutes=n)) for n in range(1, 61)]})

        def get_market_indices(self, market):
            return []

        def get_index_history(self, *args, **kwargs):
            return history, NOW

    builder = ReviewContextBuilder(
        market_data=Data(),
        resolver=NS(get_resolved_portfolio=lambda *a, **k: portfolio),
        previews=Previews(),
        instruments=NS(names_by_codes=lambda s: {"600519.SH": "茅台"}),
    )
    result = builder.build(1, "CN", NOW, NOW.replace(hour=15))
    holding = result["holdings"][0]
    assert holding["quantity"] == 100 and holding["current_price"] == 101
    assert len(holding["daily_bars"]) == 20 and len(holding["minute_bars"]) == 12
    assert holding["daily_bars"][-1][0] == "2026-10-29"
    assert result["portfolio"]["nav"] == 20100
    assert "DO_NOT_SEND" not in str(result)
    assert builder._preview("industry_strength", "US", NOW)["status"] == "unsupported"

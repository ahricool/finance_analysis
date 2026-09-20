"""Completed daily-bar cutoff and quote fetch. Fake providers only."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.models import (  # pragma: allowlist secret
    Adjustment,
    BatchBarResult,
    Market,
    MarketBar,
)
from finance_analysis.trade_engine.market import RiskMarketGateway  # pragma: allowlist secret
from finance_analysis.trade_engine.models import QuoteView  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


class FakeMarket:
    def __init__(self):
        self.daily_calls = []
        self.quote_calls = []
        self.daily_rows = []

    def get_realtime_quotes(self, symbols, providers=None):
        self.quote_calls.append(list(symbols))
        return type("R", (), {"data": {}})()

    def get_daily_bars(self, symbols, start, end, **kwargs):
        self.daily_calls.append({"symbols": list(symbols), "start": start, "end": end})
        result = BatchBarResult()
        for symbol in symbols:
            result.data[symbol] = list(self.daily_rows)
            result.providers_used[symbol] = "db"
        return result


def _daily(symbol, trade_date):
    return MarketBar(
        symbol=symbol,
        market=Market.US,
        interval="1d",
        trade_date=trade_date,
        bar_time=datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=UTC),
        open=10,
        high=11,
        low=9,
        close=10,
        volume=100,
        amount=None,
        currency="USD",
        adjustment=Adjustment.FORWARD,
        provider="db",
    )


def test_intraday_remote_daily_is_dropped_before_strategies(monkeypatch):
    fake = FakeMarket()
    fake.daily_rows = [_daily("AAPL.US", date(2026, 9, 18)), _daily("AAPL.US", date(2026, 9, 21))]
    monkeypatch.setattr(
        "finance_analysis.trade_engine.market.latest_completed_trading_day",  # pragma: allowlist secret
        lambda market, now: date(2026, 9, 18),
    )
    gateway = RiskMarketGateway(market_data=fake)
    now = datetime(2026, 9, 21, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    bars = gateway.daily_bars(["AAPL.US"], start=date(2026, 9, 1), end=now.date(), now=now)
    assert [bar.trade_date for bar in bars["AAPL.US"]] == [date(2026, 9, 18)]


def test_quotes_mark_missing_as_invalid_instead_of_zero_price_valid():
    gateway = RiskMarketGateway(market_data=FakeMarket())
    now = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)
    quotes = gateway.quotes(["AAPL.US"], now=now)
    assert quotes["AAPL.US"] == QuoteView(price=Decimal("0"), quote_as_of=None, valid=False)

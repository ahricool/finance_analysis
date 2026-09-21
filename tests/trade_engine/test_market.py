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
        self.daily_calls.append({"symbols": list(symbols), "start": start, "end": end, "source_policy": kwargs.get("source_policy")})
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
    assert fake.daily_calls[0]["source_policy"] == "db_latest"


def test_quotes_mark_missing_as_invalid_instead_of_zero_price_valid():
    gateway = RiskMarketGateway(market_data=FakeMarket())
    now = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)
    quotes = gateway.quotes(["AAPL.US"], now=now)
    assert quotes["AAPL.US"].price is None
    assert quotes["AAPL.US"].valid is False
    assert quotes["AAPL.US"].today_open is None
    assert quotes["AAPL.US"].today_volume is None
    assert quotes["AAPL.US"].today_turnover is None
    assert quotes["AAPL.US"].today_high is None
    assert quotes["AAPL.US"].today_low is None


def test_quote_missing_ohlcv_stays_null_instead_of_zero():
    class FakeQuote:
        price = 200
        quote_time = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)
        open_price = None
        high = None
        low = None
        volume = None
        amount = None
        pre_close = None
        change_pct = None

    class WithQuote(FakeMarket):
        def get_realtime_quotes(self, symbols, providers=None):
            return type("R", (), {"data": {symbols[0]: FakeQuote()}})()

    gateway = RiskMarketGateway(market_data=WithQuote())
    now = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)
    quote = gateway.quotes(["AAPL.US"], now=now)["AAPL.US"]
    assert quote.price == Decimal("200")
    assert quote.today_open is None
    assert quote.today_high is None
    assert quote.today_low is None
    assert quote.today_volume is None
    assert quote.today_turnover is None
    assert quote.pre_close is None
    assert quote.change_pct is None


def test_fresh_streaming_quote_retains_received_time_through_market_data(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from finance_analysis.integrations.market_data.realtime_state.data_source import (
        RealtimeMarketDataSource,
        SyncRealtimeMarketDataSource,
    )
    from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
    from finance_analysis.integrations.market_data.registry import ProviderRegistry, REALTIME_QUOTES
    from finance_analysis.integrations.market_data.service import MarketDataService, _StreamingStateProvider

    now = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)
    state = QuoteState(
        symbol="AAPL.US", trading_date=now.date(), last_price=Decimal("105"),
        open=Decimal("100"), high=Decimal("106"), low=Decimal("99"), volume=123456,
        event_time=now, received_at=now,
    )
    repository = SimpleNamespace(
        get_heartbeat=AsyncMock(return_value={"status": "READY", "updated_at": now.isoformat()}),
        get_subscription=AsyncMock(return_value={"status": "ACTIVE", "market_type": "US"}),
        get_quote=AsyncMock(return_value=state),
        close=AsyncMock(),
    )
    monkeypatch.setattr("finance_analysis.integrations.market_data.realtime_state.data_source.utc_now", lambda: now)
    source = SyncRealtimeMarketDataSource(lambda: RealtimeMarketDataSource(repository))
    try:
        unified = source.get_quote("AAPL.US", now=now)
        assert unified.quote_time == state.received_at
        registry = ProviderRegistry()
        registry.register("streaming", _StreamingStateProvider(source), capabilities={REALTIME_QUOTES})
        gateway = RiskMarketGateway(market_data=MarketDataService(registry=registry))
        view = gateway.quotes(["AAPL.US"], now=now)["AAPL.US"]
        assert view.valid is True
        assert view.quote_as_of == state.received_at
        # Missing exchange time uses the same internal receive timestamp.
        state.event_time = None
        assert source.get_quote("AAPL.US", now=now).quote_time == state.received_at
    finally:
        source.close()

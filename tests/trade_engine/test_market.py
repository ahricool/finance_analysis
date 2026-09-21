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


def test_us_yfinance_fallback_has_snapshot_time(monkeypatch):
    from datetime import timezone
    from types import SimpleNamespace
    import yfinance

    from finance_analysis.integrations.market_data.models import BatchQuoteResult, QuoteRequest
    from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider
    from finance_analysis.integrations.market_data.registry import ProviderRegistry, REALTIME_QUOTES
    from finance_analysis.integrations.market_data.service import MarketDataService

    monkeypatch.setattr(yfinance, "Ticker", lambda symbol: SimpleNamespace(fast_info={
        "last_price": 100, "previous_close": 99, "open": 99,
        "day_high": 101, "day_low": 98, "last_volume": 123456,
    }))
    provider = YFinanceProvider()
    before = datetime.now(timezone.utc)
    quote = provider.fetch_quotes(QuoteRequest(("AAPL.US",))).data["AAPL.US"]
    assert before <= quote.quote_time <= datetime.now(timezone.utc)
    assert quote.quote_time.utcoffset().total_seconds() == 0

    calls = []

    class Missing:
        def __init__(self, name):
            self.name = name

        def fetch_quotes(self, request):
            calls.append(self.name)
            return BatchQuoteResult(missing_symbols=list(request.symbols))

    registry = ProviderRegistry()
    registry.register("streaming", Missing("streaming"), capabilities={REALTIME_QUOTES})
    registry.register("longbridge", Missing("longbridge"), capabilities={REALTIME_QUOTES})
    registry.register("yfinance", provider, capabilities={REALTIME_QUOTES})
    service = MarketDataService(registry=registry)
    result = service.get_realtime_quotes(["AAPL.US"])
    assert result.providers_used["AAPL.US"] == "yfinance"
    assert calls == ["streaming", "longbridge"]
    view = RiskMarketGateway(market_data=service).quotes(["AAPL.US"])["AAPL.US"]
    assert view.valid is True
    assert view.quote_as_of is not None


def test_longbridge_pull_preserves_timestamp_or_uses_fetch_time(monkeypatch):
    from datetime import timezone
    from types import SimpleNamespace
    from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeProvider

    provider = object.__new__(LongbridgeProvider)
    raw = SimpleNamespace(last_done=100, timestamp=None)
    monkeypatch.setattr(provider, "is_available_for_request", lambda request: True)
    monkeypatch.setattr(provider, "_get_ctx", lambda: SimpleNamespace(quote=lambda symbols: [raw]))
    monkeypatch.setattr(provider, "_get_static_info", lambda symbol: None)
    monkeypatch.setattr(provider, "_compute_volume_ratio", lambda symbol, volume: None)
    before = datetime.now(timezone.utc)
    quote = provider.get_realtime_quote("AAPL.US")
    assert before <= quote.quote_time <= datetime.now(timezone.utc)
    assert quote.quote_time.utcoffset().total_seconds() == 0
    raw.timestamp = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    assert provider.get_realtime_quote("AAPL.US").quote_time == raw.timestamp


def test_fuyao_snapshot_preserves_timestamp_or_uses_fetch_time(monkeypatch):
    from datetime import timezone
    from finance_analysis.integrations.market_data.models import QuoteRequest
    from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider

    provider = FuyaoProvider(api_key="test")
    payload = {"item": [{"thscode": "600519.SH", "last_price": 100, "asset_type": "a-share"}]}
    monkeypatch.setattr(provider, "_get", lambda *args, **kwargs: payload)
    before = datetime.now(timezone.utc)
    quote = provider.fetch_quotes(QuoteRequest(("600519.SH",))).data["600519.SH"]
    assert before <= quote.quote_time <= datetime.now(timezone.utc)
    stamp = datetime(2026, 9, 16, 7, 0, tzinfo=timezone.utc)
    payload["timestamp"] = int(stamp.timestamp() * 1000)
    assert provider.fetch_quotes(QuoteRequest(("600519.SH",))).data["600519.SH"].quote_time == stamp

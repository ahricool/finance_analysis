"""5m cache sharing, stale-on-failure, and quote/5m decoupling. Fake providers only."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.config import portfolio_risk_minute_providers  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import BatchBarResult, Market, MarketBar, Adjustment  # pragma: allowlist secret
from finance_analysis.trade_engine.market import MinuteBarCache, RiskMarketGateway  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


class MemoryRedis(dict):
    def get(self, key):
        return dict.get(self, key)

    def set(self, key, value, ex=None):
        self[key] = value


class FakeMarket:
    def __init__(self):
        self.minute_calls = []
        self.quote_calls = []

    def get_realtime_quotes(self, symbols, providers=None):
        self.quote_calls.append(list(symbols))
        return type("R", (), {"data": {}})()

    def get_minute_bars(self, symbols, start, end, *, interval="5m", providers=None, period=None):
        self.minute_calls.append({"symbols": list(symbols), "providers": tuple(providers or ()), "period": period, "interval": interval})
        result = BatchBarResult()
        for symbol in symbols:
            if str(symbol).endswith(".US"):
                zone = ZoneInfo("America/New_York")
                market = Market.US
                provider = "yfinance"
                currency = "USD"
                amount = None
            else:
                zone = SH
                market = Market.CN
                provider = "sina_minute"
                currency = "CNY"
                amount = 1000
            end_local = datetime(2026, 9, 16, 9, 35, tzinfo=zone)
            result.data[symbol] = [
                MarketBar(
                    symbol=symbol,
                    market=market,
                    interval="5m",
                    trade_date=end_local.date(),
                    bar_time=end_local.astimezone(UTC),
                    open=10,
                    high=11,
                    low=9,
                    close=10,
                    volume=100,
                    amount=amount,
                    currency=currency,
                    adjustment=Adjustment.RAW,
                    provider=provider,
                    bar_start=(end_local - timedelta(minutes=5)).astimezone(UTC),
                    bar_end=end_local.astimezone(UTC),
                )
            ]
            result.providers_used[symbol] = provider
        return result


def test_portfolio_risk_minute_providers_are_explicit_and_not_default_fallback():
    assert portfolio_risk_minute_providers("CN") == ("sina_minute",)
    assert portfolio_risk_minute_providers("US") == ("yfinance",)


def test_multiple_legs_share_one_minute_request_and_cache():
    fake = FakeMarket()
    gateway = RiskMarketGateway(market_data=fake, cache=MinuteBarCache(MemoryRedis()))
    now = datetime(2026, 9, 16, 9, 40, tzinfo=SH)
    start = now - timedelta(days=5)
    first = gateway.five_minute_bars(["600519.SH", "600519.SH"], start=start, end=now, now=now, refresh=True)
    second = gateway.five_minute_bars(["600519.SH"], start=start, end=now, now=now, wait_refresh=False)
    assert list(first) == ["600519.SH"]
    assert second["600519.SH"]
    assert len(fake.minute_calls) == 1
    assert fake.minute_calls[0]["providers"] == ("sina_minute",)


def test_failed_refresh_keeps_cache_and_marks_stale():
    fake = FakeMarket()
    cache = MinuteBarCache(MemoryRedis())
    gateway = RiskMarketGateway(market_data=fake, cache=cache)
    now = datetime(2026, 9, 16, 9, 40, tzinfo=SH)
    start = now - timedelta(days=5)
    gateway.five_minute_bars(["600519.SH"], start=start, end=now, now=now, refresh=True)

    class Boom(FakeMarket):
        def get_minute_bars(self, *args, **kwargs):
            raise RuntimeError("sina down")

    broken = RiskMarketGateway(market_data=Boom(), cache=cache)
    later = now + timedelta(minutes=10)
    bars = broken.five_minute_bars(["600519.SH"], start=start, end=later, now=later, refresh=True)
    assert bars["600519.SH"]
    payload = cache.load("sina_minute", "600519.SH")
    assert payload["stale"] is True


def test_quotes_do_not_require_minute_history():
    fake = FakeMarket()
    gateway = RiskMarketGateway(market_data=fake, cache=MinuteBarCache(MemoryRedis()))
    gateway.quotes(["600519.SH"], now=datetime(2026, 9, 16, 9, 40, tzinfo=SH))
    assert fake.quote_calls
    assert fake.minute_calls == []


def test_slow_symbol_fetch_degrades_within_budget_without_thread_leak():
    import threading
    import time

    class SlowMarket(FakeMarket):
        def get_minute_bars(self, symbols, start, end, *, interval="5m", providers=None, period=None):
            time.sleep(2)
            return super().get_minute_bars(symbols, start, end, interval=interval, providers=providers, period=period)

    before = {thread.name for thread in threading.enumerate()}
    fake = SlowMarket()
    gateway = RiskMarketGateway(
        market_data=fake,
        cache=MinuteBarCache(MemoryRedis()),
        timeout_seconds=0.4,
        max_concurrency=2,
    )
    now = datetime(2026, 9, 16, 9, 40, tzinfo=SH)
    start = now - timedelta(days=5)
    started = time.perf_counter()
    bars = gateway.five_minute_bars(
        ["600519.SH", "000001.SZ", "600036.SH"],
        start=start,
        end=now,
        now=now,
        refresh=True,
        timeout_seconds=0.4,
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 3.5
    assert set(bars) == {"600519.SH", "000001.SZ", "600036.SH"}
    assert gateway.degraded_symbols
    leftover = [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("pr-5m") and thread.name not in before
    ]
    assert leftover == []


def test_us_cold_start_uses_one_month_then_five_day_refresh():
    fake = FakeMarket()
    cache = MinuteBarCache(MemoryRedis())
    gateway = RiskMarketGateway(market_data=fake, cache=cache)
    now = datetime(2026, 9, 16, 11, 0, tzinfo=ZoneInfo("America/New_York"))
    start = now - timedelta(days=20)
    gateway.five_minute_bars(["AAPL.US"], start=start, end=now, now=now, refresh=True)
    assert fake.minute_calls[0]["period"] == "1mo"
    assert fake.minute_calls[0]["providers"] == ("yfinance",)
    gateway.five_minute_bars(["AAPL.US"], start=start, end=now, now=now, refresh=True)
    assert fake.minute_calls[1]["period"] == "5d"

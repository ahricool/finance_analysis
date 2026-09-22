"""Offline bounded fan-out, deadline and late-result isolation tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock
from time import monotonic
from types import SimpleNamespace

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.models import BatchBarResult, QuoteRequest, MinuteBarsRequest
from finance_analysis.integrations.market_data.providers.sina_minute import SinaMinuteProvider, MINUTE_WORKERS
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider
from finance_analysis.integrations.market_data.request_budget import request_budget
from finance_analysis.intraday_confirmation import config as c
from finance_analysis.intraday_confirmation.market_data import collect_data
from finance_analysis.intraday_confirmation.session import Session
from finance_analysis.intraday_confirmation.service import ConfirmationService

NOW = datetime(2026, 9, 22, 2, 0, tzinfo=timezone.utc)
OPEN = NOW - timedelta(minutes=30)
CN_SESSION = Session("CN", OPEN, OPEN + timedelta(hours=5, minutes=30), (NOW - timedelta(days=1)).date())


def frame():
    return pd.DataFrame([dict(day="2026-09-22 09:35:00", open=100, high=102, low=99, close=101, volume=1000)])


def minute_request(symbols):
    return MinuteBarsRequest(tuple(symbols), OPEN, NOW, "5m")


def test_sina_bounded_parallel_requests_and_single_timeout():
    barrier = Barrier(MINUTE_WORKERS)
    lock = Lock()
    active = peak = 0
    calls = []

    def fetch(symbol):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(symbol)
        try:
            # Serial execution or unbounded fan-out fails this first-wave barrier.
            if int(symbol[2:]) < 600001 + MINUTE_WORKERS:
                barrier.wait(timeout=3)
            if symbol == "sh600001":
                raise TimeoutError("one symbol timed out")
            return frame()
        finally:
            with lock:
                active -= 1

    codes = [f"{600001+i}.SH" for i in range(MINUTE_WORKERS + 3)]
    result = SinaMinuteProvider(fetch_frame=fetch).fetch_minute_bars(minute_request(codes))
    assert peak == MINUTE_WORKERS
    assert len(calls) == len(codes)
    assert set(result.data) == set(codes) - {"600001.SH"}
    assert result.failed_symbols == result.request_errors == {"600001.SH": "one symbol timed out"}
    bar = result.data["600002.SH"][0]
    assert bar.bar_time == bar.bar_end == OPEN + timedelta(minutes=5)
    assert bar.bar_start == OPEN


def info():
    return dict(
        regularMarketTime=int(NOW.timestamp()),
        regularMarketPrice=101,
        regularMarketOpen=100,
        regularMarketDayHigh=102,
        regularMarketDayLow=99,
        regularMarketPreviousClose=98,
        regularMarketVolume=1234,
    )


def test_yahoo_quotes_parallel_failure_isolated_and_exchange_time_preserved(monkeypatch):
    import yfinance

    barrier = Barrier(3)

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            barrier.wait(timeout=3)
            if self.symbol == "BAD":
                raise ValueError("unavailable ticker")
            data = info()
            if self.symbol == "NO_TIME":
                data.pop("regularMarketTime")
            return data

    monkeypatch.setattr(yfinance, "Ticker", Ticker)
    result = YFinanceProvider(max_workers=3).fetch_quotes(QuoteRequest(("GOOD.US", "BAD.US", "NO_TIME.US")))
    assert set(result.data) == {"GOOD.US", "NO_TIME.US"}
    assert result.failed_symbols == {"BAD.US": "unavailable ticker"}
    q = result.data["GOOD.US"]
    assert (q.price, q.open_price, q.high, q.low, q.pre_close, q.volume) == (101, 100, 102, 99, 98, 1234)
    assert q.quote_time == NOW
    assert result.data["NO_TIME.US"].quote_time is None


def test_sina_deadline_returns_completed_symbols_without_waiting_for_slow_sdk():
    release, entered = Event(), Event()

    def fetch(symbol):
        if symbol == "sh600001":
            entered.set()
            assert release.wait(timeout=5)
        return frame()

    provider = SinaMinuteProvider(fetch_frame=fetch)
    try:
        started = monotonic()
        with request_budget(1.2):
            result = provider.fetch_minute_bars(minute_request(["600001.SH", "600002.SH"]))
        assert entered.is_set() and not release.is_set()
        assert monotonic() - started < 2.5
        assert list(result.data) == ["600002.SH"]
        assert result.failed_symbols["600001.SH"] == result.request_errors["600001.SH"] == "skipped_budget"
    finally:
        release.set()
    # The worker returns a value to its future; it cannot mutate the published batch.
    assert list(result.data) == ["600002.SH"]


def test_phase_budget_stops_waiting_for_uncooperative_source(monkeypatch):
    monkeypatch.setattr(c, "MARKET_DATA_BUDGET_SECONDS", 1.3)
    monkeypatch.setattr(c, "MARKET_DATA_RETURN_RESERVE_SECONDS", 0.1)
    release, entered = Event(), Event()

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return BatchBarResult(data={"600001.SH": ["late"]})

    md = SimpleNamespace(
        get_realtime_quotes=lambda *a, **kw: SimpleNamespace(data={"600001.SH": "quote"}),
        get_minute_bars=slow,
        get_daily_bars=lambda *a, **kw: BatchBarResult(),
    )
    try:
        started = monotonic()
        quotes, minute, history = collect_data(md, ["600001.SH"], CN_SESSION, NOW)
        assert entered.is_set() and not release.is_set()
        assert monotonic() - started < 2.5
        assert quotes == {"600001.SH": "quote"}
        assert minute == history == {}
    finally:
        release.set()
    assert minute == {}


def test_budget_keeps_provider_partial_data_and_publishes_missing_candidate_wait(monkeypatch):
    from finance_analysis.integrations.market_data import MarketDataService
    from finance_analysis.integrations.market_data.models import BatchQuoteResult, MarketQuote, Market
    from finance_analysis.integrations.market_data.registry import ProviderRegistry, REALTIME_QUOTES, MINUTE_BARS

    monkeypatch.setattr(c, "MARKET_DATA_BUDGET_SECONDS", 1.5)
    monkeypatch.setattr(c, "MARKET_DATA_RETURN_RESERVE_SECONDS", 0.2)
    release = Event()
    entered = Event()

    def fetch(symbol):
        if symbol == "sh600001":
            entered.set()
            assert release.wait(timeout=5)
        return frame()

    class Quotes:
        def fetch_quotes(self, request):
            return BatchQuoteResult(
                data={
                    code: MarketQuote(
                        symbol=code,
                        market=Market.CN,
                        provider="easyquotation",
                        currency="CNY",
                        price=101,
                        open_price=100,
                        high=102,
                        low=99,
                        pre_close=100,
                        volume=1000,
                        quote_time=NOW,
                    )
                    for code in request.symbols
                }
            )

    registry = ProviderRegistry()
    registry.register("easyquotation", Quotes(), capabilities={REALTIME_QUOTES})
    registry.register("sina_minute", SinaMinuteProvider(fetch_frame=fetch), capabilities={MINUTE_BARS})
    md = MarketDataService(registry=registry)
    monkeypatch.setattr(md, "get_daily_bars", lambda *a, **kw: BatchBarResult())

    class Cache:
        def save(self, session, payload):
            self.payload = payload

    cache = Cache()
    payload = dict(items=[dict(code=code, state="WAIT") for code in ("600001.SH", "600002.SH")])
    try:
        service = ConfirmationService(cache=cache, market_data=md)
        service._evaluate(CN_SESSION, payload, NOW)
        assert entered.is_set() and not release.is_set()
        slow, fast = cache.payload["items"]
        assert slow["state"] == "WAIT" and slow["metrics"]["return_5m"] is None
        assert slow["metrics"]["vwap"] is None
        assert fast["metrics"]["return_5m"] == pytest.approx(0.01)
        assert fast["metrics"]["quote_time"] == NOW
        assert fast["metrics"]["bar_time"] == OPEN + timedelta(minutes=5)
    finally:
        release.set()


def test_expired_queued_requests_do_not_start_and_executor_is_not_joined():
    from finance_analysis.integrations.market_data.bounded_requests import bounded_results

    release, entered = Event(), Event()
    calls = []

    def slow():
        entered.set()
        assert release.wait(timeout=5)
        return 1

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        with request_budget(1):
            results = list(bounded_results({"slow": slow, "queued": lambda: calls.append("queued")}, executor, 1))
        assert entered.is_set() and not release.is_set()
        assert all(isinstance(error, TimeoutError) for _, _, error in results)
        assert not calls
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_yahoo_deadline_returns_partial_quotes_and_late_error_does_not_retry(monkeypatch, external_retry_waits):
    import yfinance

    release, finished = Event(), Event()
    attempts = []

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            if self.symbol == "SLOW":
                attempts.append(self.symbol)
                assert release.wait(timeout=5)
                finished.set()
                raise TimeoutError("late timeout")
            return info()

    monkeypatch.setattr(yfinance, "Ticker", Ticker)
    try:
        with request_budget(1.1):
            result = YFinanceProvider(max_workers=2).fetch_quotes(QuoteRequest(("SLOW.US", "FAST.US")))
        assert result.failed_symbols == {"SLOW.US": "skipped_budget"}
        assert list(result.data) == ["FAST.US"]
        assert result.data["FAST.US"].quote_time == NOW
        assert not release.is_set()
    finally:
        release.set()
    assert finished.wait(timeout=2)
    assert attempts == ["SLOW"]
    external_retry_waits[0].assert_not_called()


def test_sina_sdk_call_does_not_change_process_socket_defaults(monkeypatch):
    import akshare
    import socket
    from finance_analysis.integrations.market_data.providers.sina_minute import _akshare_minute
    from unittest.mock import Mock

    defaults = Mock(side_effect=AssertionError("global socket mutation"))
    monkeypatch.setattr(socket, "setdefaulttimeout", defaults)
    fetch = Mock(return_value=frame())
    monkeypatch.setattr(akshare, "stock_zh_a_minute", fetch)
    assert len(_akshare_minute("sh600001")) == 1
    fetch.assert_called_once_with(symbol="sh600001", period="5", adjust="")
    defaults.assert_not_called()

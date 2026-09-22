"""Offline contract and synchronization routing checks for Alpaca."""

from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from finance_analysis.integrations.market_data.config import DataProviderConfig, get_data_provider_config
from finance_analysis.integrations.market_data.models import Adjustment, BatchBarResult, DailyBarsRequest, Market
from finance_analysis.integrations.market_data.providers import alpaca
from finance_analysis.integrations.market_data.registry import DAILY_BARS, ProviderRegistry
from finance_analysis.integrations.market_data.service import MarketDataService, build_default_registry
from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService

DAY = date(2025, 1, 2)


def row(timestamp="2025-01-02T05:00:00Z", **kwargs):
    return {"t": timestamp, "o": 10, "h": 12, "l": 9, "c": 11, "v": 100, "vw": 10.75, **kwargs}


def request(symbols=("NVDA.US", "MU.US"), start=DAY, end=DAY):
    return DailyBarsRequest(symbols, start, end, Adjustment.FORWARD)


def provider(handler, **kwargs):
    return alpaca.AlpacaProvider(
        api_key="test-key", secret_key="test-secret", transport=httpx.MockTransport(handler), **kwargs,
    )


@pytest.fixture(autouse=True)
def no_batch_wait(monkeypatch):
    monkeypatch.setattr("finance_analysis.integrations.market_data.batch_pacing.sleep", lambda _: None)


def test_batch_pagination_conversion_and_recent_sip_end(monkeypatch):
    now = datetime(2025, 1, 3, 2, tzinfo=timezone.utc)  # 21:00 NY on January 2
    monkeypatch.setattr(alpaca, "utc_now", lambda: now)
    calls = []

    def handler(req):
        calls.append(req)
        assert req.url.host == "data.alpaca.markets"
        assert req.headers["APCA-API-KEY-ID"] == "test-key"
        assert req.headers["APCA-API-SECRET-KEY"] == "test-secret"
        assert req.url.params["symbols"] == "NVDA,MU"
        assert req.url.params["adjustment"] == "all"
        assert req.url.params["feed"] == "sip"
        assert req.url.params["timeframe"] == "1Day"
        assert req.url.params["limit"] == "10000"
        assert req.url.params["start"] == "2025-01-02T05:00:00+00:00"
        assert req.url.params["end"] == "2025-01-03T01:44:00+00:00"
        if "page_token" not in req.url.params:
            return httpx.Response(200, json={"bars": {"MU": [row()]}, "next_page_token": "next"})
        assert req.url.params["page_token"] == "next"
        return httpx.Response(200, json={"bars": {"NVDA": [row()]}, "next_page_token": None})

    result = provider(handler).fetch_daily_bars(request())
    assert len(calls) == 2
    assert set(result.data) == {"NVDA.US", "MU.US"}
    bar = result.data["NVDA.US"][0]
    assert bar.market is Market.US and bar.adjustment is Adjustment.FORWARD
    assert (bar.trade_date, bar.bar_time, bar.currency, bar.provider) == (DAY, None, "USD", "alpaca")
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (10, 12, 9, 11, 100)
    assert bar.amount is None  # VWAP * adjusted volume is not a reported traded amount.
    assert result.request_errors == result.failed_symbols == {}


def test_ny_date_dst_and_share_class_mapping():
    # Midnight UTC is the preceding NY trading date; do not just strip the timestamp.
    def handler(req):
        assert req.url.params["symbols"] == "BRK.B"
        assert req.url.params["start"] == "2025-07-01T04:00:00+00:00"
        return httpx.Response(200, json={"bars": {"BRK.B": [row("2025-07-02T00:00:00Z")]}})

    result = provider(handler).fetch_daily_bars(request(("BRK.B.US",), date(2025, 7, 1), date(2025, 7, 1)))
    assert result.data["BRK.B.US"][0].trade_date == date(2025, 7, 1)


def test_http_batches_are_bounded_and_failed_batch_does_not_drop_successes():
    calls = []

    def handler(req):
        symbols = req.url.params["symbols"].split(",")
        calls.append(symbols)
        if len(calls) == 2:
            return httpx.Response(500)
        return httpx.Response(200, json={"bars": {s: [row()] for s in symbols}})

    symbols = tuple(f"S{i}.US" for i in range(205))
    result = provider(handler).fetch_daily_bars(request(symbols))
    assert [len(c) for c in calls] == [100, 100, 5]
    assert len(result.data) == 105
    assert set(result.failed_symbols) == set(symbols[100:200])


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_stops_remaining_batches(status, caplog):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(status, text="test-secret must never be logged")

    result = provider(handler, batch_size=1).fetch_daily_bars(request())
    assert len(calls) == 1 and len(result.failed_symbols) == 2
    assert "test-secret" not in caplog.text


@pytest.mark.parametrize("broken", [row(c=20), row(v=-1), row(v=0.5), row(t="2025-01-02"), {"bad": 1}])
def test_single_bad_symbol_isolated(broken):
    result = provider(lambda _: httpx.Response(200, json={"bars": {"NVDA": [row()], "MU": [broken]}})).fetch_daily_bars(
        request()
    )
    assert set(result.data) == {"NVDA.US"}
    assert result.failed_symbols == {"MU.US": "invalid_daily_bars"}


def test_missing_session_rejects_whole_symbol_window_for_fallback():
    result = provider(lambda _: httpx.Response(200, json={"bars": {"NVDA": [row()]}})).fetch_daily_bars(
        request(("NVDA.US",), DAY, date(2025, 1, 3))
    )
    assert not result.data
    assert result.failed_symbols == {"NVDA.US": "incomplete_daily_window"}


@pytest.mark.parametrize("failure", ["http", "token"])
def test_incomplete_pagination_never_returns_truncated_history(failure):
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) > 1 and failure == "http":
            return httpx.Response(503)
        return httpx.Response(200, json={"bars": {"MU": [row()]}, "next_page_token": "same"})

    result = provider(handler).fetch_daily_bars(request())
    assert len(calls) == 2
    assert not result.data and len(result.failed_symbols) == 2


def service(first, *, final_error=False):
    calls = []

    def yahoo(req):
        calls.append(req.symbols)
        data = {s: [replace(alpaca.AlpacaProvider._bar(s, row()), provider="yfinance")] for s in req.symbols}
        return BatchBarResult(
            data=data, providers_used={s: "yfinance" for s in data},
            request_errors={s: "partial download" for s in data} if final_error else {},
        )

    registry = ProviderRegistry()
    registry.register("alpaca", first, capabilities={DAILY_BARS})
    registry.register("yfinance", SimpleNamespace(fetch_daily_bars=yahoo), capabilities={DAILY_BARS})
    return MarketDataService(registry, daily_sync=True), calls


@pytest.mark.parametrize("mode", ["no_key", "http", "timeout", "empty", "unsupported", "malformed"])
def test_fallback_conditions_recover_with_yahoo(mode):
    def handler(req):
        if mode == "timeout":
            raise httpx.ReadTimeout("timeout", request=req)
        if mode == "http":
            return httpx.Response(429)
        if mode == "malformed":
            return httpx.Response(200, json={"bars": {"NVDA": [row(c=50)]}})
        return httpx.Response(200, json={"bars": {}})

    first = alpaca.AlpacaProvider() if mode == "no_key" else provider(handler)
    data, calls = service(first)
    symbol = "^SPX.US" if mode == "unsupported" else "NVDA.US"
    result = data.get_daily_bars([symbol], DAY, DAY, adjustment="forward", source_policy="remote_only")
    assert calls == [(symbol,)]
    assert result.providers_used[symbol] == "yfinance"
    assert result.request_errors == result.failed_symbols == {}
    assert result.fallback_reasons[symbol]


def test_fallback_only_requests_failed_symbols_and_preserves_final_error():
    first = provider(lambda _: httpx.Response(200, json={"bars": {"NVDA": [row()]}}))
    data, calls = service(first, final_error=True)
    result = data.get_daily_bars(["NVDA.US", "MU.US"], DAY, DAY, adjustment="forward", source_policy="remote_only")
    assert calls == [("MU.US",)]
    assert result.providers_used == {"NVDA.US": "alpaca", "MU.US": "yfinance"}
    assert "MU.US" in result.request_errors  # full refresh must still refuse this incomplete fallback.


def test_full_sync_can_persist_complete_fallback_and_records_metrics(caplog):
    # Exercise the normal sync constructor, configuration and full-history write path without a DB.
    stored = {}
    repo = SimpleNamespace(
        has_daily_data=lambda _: True,
        replace_daily_history=lambda identity, rows, source: (
            stored.update({identity: rows}) or SimpleNamespace(inserted_rows=len(rows), updated_rows=0, deleted_rows=0)
        ),
        daily_ids_on_date=lambda ids, day: {i for i in ids if any(r["date"] == day for r in stored.get(i, []))},
    )
    data, calls = service(alpaca.AlpacaProvider())
    sync = MarketDataSyncService(
        "US", stock_repository=repo, market_data_service=data,
        universe_resolver=SimpleNamespace(), config=DataProviderConfig(), sync_mode="full",
    )
    sync.load_scope = lambda: [SimpleNamespace(id=1, code="NVDA.US")]
    sync._refresh_days = lambda _: [DAY]
    with caplog.at_level("INFO"):
        result = sync.run()
    assert result["sync_status"] == "success"
    assert result["provider_counts"] == {"yfinance": 1}
    assert result["fallback_count"] == 1 and result["final_coverage"] == 1
    assert stored[1][0]["data_source"] == "yfinance"
    assert "fallback_count=1" in caplog.text and "elapsed_seconds=" in caplog.text


def test_config_credentials_and_sync_scope(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    get_data_provider_config.cache_clear()
    try:
        config = get_data_provider_config()
        assert config.alpaca_api_key == "test-key" and config.alpaca_secret_key == "test-secret"
        assert "test-secret" not in repr(config) and "test-key" not in repr(config)
        registry = build_default_registry(config)
        assert registry.capabilities("alpaca") == {DAILY_BARS}
        assert registry.get("alpaca").provider._api_key == "test-key"
    finally:
        get_data_provider_config.cache_clear()

    data, calls = service(provider(lambda _: pytest.fail("ordinary reads must not call Alpaca")))
    data.daily_sync = False
    result = data.get_daily_bars(["NVDA.US"], DAY, DAY, adjustment="forward", source_policy="remote_only")
    assert calls == [("NVDA.US",)] and result.providers_used["NVDA.US"] == "yfinance"


def test_sync_constructor_enables_maintenance_routing():
    sync = MarketDataSyncService(
        "US", stock_repository=SimpleNamespace(), universe_resolver=SimpleNamespace(), config=DataProviderConfig(),
    )
    assert sync.market_data.daily_sync is True


def test_sync_saves_success_when_other_symbol_fails_both_providers(monkeypatch):
    stored = {}
    monkeypatch.setattr("finance_analysis.tasks.celery.jobs.market_data_sync.service.sleep", lambda _: None)
    first = provider(lambda _: httpx.Response(200, json={"bars": {"NVDA": [row()]}}))
    registry = ProviderRegistry()
    registry.register("alpaca", first, capabilities={DAILY_BARS})
    registry.register(
        "yfinance", SimpleNamespace(fetch_daily_bars=lambda req: BatchBarResult(
            failed_symbols={s: "download_failed" for s in req.symbols},
        )), capabilities={DAILY_BARS},
    )
    repo = SimpleNamespace(
        has_daily_data=lambda _: True,
        upsert_daily=lambda identity, rows, source: (
            stored.update({identity: rows}) or SimpleNamespace(inserted_rows=len(rows), updated_rows=0)
        ),
        daily_ids_on_date=lambda ids, day: {i for i in ids if any(r["date"] == day for r in stored.get(i, []))},
    )
    sync = MarketDataSyncService(
        "US", stock_repository=repo, universe_resolver=SimpleNamespace(), config=DataProviderConfig(),
        market_data_service=MarketDataService(registry, daily_sync=True),
    )
    sync.load_scope = lambda: [SimpleNamespace(id=1, code="NVDA.US"), SimpleNamespace(id=2, code="MU.US")]
    sync._refresh_days = lambda _: [DAY]
    result = sync.run()
    assert result["sync_status"] == "partial"
    assert result["success_symbols"] == result["failed_symbols"] == 1
    assert result["remaining_missing_symbols"] == ["MU.US"]
    assert set(stored) == {1} and stored[1][0]["data_source"] == "alpaca"

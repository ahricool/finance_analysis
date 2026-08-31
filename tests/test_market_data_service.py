from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.config import DataProviderConfig, provider_order
from finance_analysis.integrations.market_data.models import (
    Adjustment,
    AdjustmentFactor,
    AdjustmentRequest,
    AdjustmentResult,
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentInfo,
    Market,
    MarketBar,
    MarketQuote,
)
from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider
from finance_analysis.integrations.market_data.registry import (
    ADJUSTMENT_FACTORS,
    DAILY_BARS,
    LATEST_MARKET_SNAPSHOT,
    MINUTE_BARS,
    ProviderConfigurationError,
    ProviderRegistry,
)
from finance_analysis.integrations.market_data.service import MarketDataService, build_default_registry
from finance_analysis.tasks.celery.jobs.market_data_sync.models import AdjustmentResult as SyncAdjustmentResult
from finance_analysis.tasks.celery.jobs.market_data_sync.models import SymbolResult
from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService


def _bar(symbol: str, provider: str, *, amount=None) -> MarketBar:
    return MarketBar(
        symbol=symbol,
        market=Market.CN,
        interval="1d",
        trade_date=date(2025, 1, 2),
        bar_time=None,
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume=100,
        amount=amount,
        currency="CNY",
        adjustment=Adjustment.RAW,
        provider=provider,
    )


class _DailyProvider:
    def __init__(self, name: str, values: dict[str, list[MarketBar]]) -> None:
        self.name = name
        self.values = values
        self.requests = []

    def fetch_daily_bars(self, request):
        self.requests.append(request)
        return BatchBarResult(
            data={symbol: self.values[symbol] for symbol in request.symbols if symbol in self.values},
            missing_symbols=[symbol for symbol in request.symbols if symbol not in self.values],
        )


def test_explicit_provider_order_is_validated_before_io():
    registry = ProviderRegistry()
    provider = _DailyProvider("daily", {})
    registry.register("daily", provider, capabilities={DAILY_BARS})
    service = MarketDataService(registry)

    with pytest.raises(ProviderConfigurationError, match="do not support"):
        service.get_minute_bars(
            ["600000.SH"],
            datetime(2025, 1, 2, tzinfo=timezone.utc),
            datetime(2025, 1, 3, tzinfo=timezone.utc),
            providers=["daily"],
        )

    assert provider.requests == []


def test_router_falls_back_per_symbol_in_declared_order():
    first = _DailyProvider("first", {"600000.SH": [_bar("600000.SH", "first")]})
    second = _DailyProvider("second", {"000001.SZ": [_bar("000001.SZ", "second")]})
    registry = ProviderRegistry()
    registry.register("first", first, capabilities={DAILY_BARS})
    registry.register("second", second, capabilities={DAILY_BARS})
    service = MarketDataService(registry)

    result = service.get_daily_bars(
        ["600000.SH", "000001.SZ"],
        date(2025, 1, 1),
        date(2025, 1, 3),
        adjustment="raw",
        providers=["first", "second"],
    )

    assert result.providers_used == {"600000.SH": "first", "000001.SZ": "second"}
    assert second.requests[0].symbols == ("000001.SZ",)


def test_amount_is_not_estimated_when_provider_omits_it():
    provider = _DailyProvider("daily", {"600000.SH": [_bar("600000.SH", "daily")]})
    registry = ProviderRegistry()
    registry.register("daily", provider, capabilities={DAILY_BARS})
    result = MarketDataService(registry).get_daily_bars(
        ["600000.SH"], date(2025, 1, 1), date(2025, 1, 3), adjustment="raw", providers=["daily"]
    )
    bar = result.data["600000.SH"][0]
    assert bar.amount is None
    assert bar.amount_estimated is False


def test_default_orders_are_explicit_and_not_integer_priorities():
    assert provider_order(Market.CN, DAILY_BARS) == ("tickflow", "akshare", "pytdx", "baostock", "yfinance")
    assert provider_order(Market.CN, DAILY_BARS)[0] == "tickflow"
    assert "longbridge" not in provider_order(Market.CN, DAILY_BARS)
    assert provider_order(Market.US, DAILY_BARS) == ("yfinance", "tickflow", "akshare")
    assert provider_order(Market.US, DAILY_BARS)[0] == "yfinance"
    assert "longbridge" not in provider_order(Market.US, DAILY_BARS)
    assert provider_order(Market.CN, MINUTE_BARS) == ("streaming", "longbridge", "efinance", "pytdx", "akshare")
    assert provider_order(Market.CN, ADJUSTMENT_FACTORS) == ("akshare", "tickflow", "yfinance")


def test_default_registry_excludes_unsupported_efinance_daily_and_includes_tickflow_factors():
    registry = build_default_registry()
    assert DAILY_BARS not in registry.capabilities("efinance")
    assert ADJUSTMENT_FACTORS in registry.capabilities("tickflow")


def test_tickflow_free_uses_maximum_history_count_native_batch_raw_and_cn_lots_become_shares():
    calls = []

    class _Klines:
        def batch(self, symbols, **kwargs):
            calls.append((symbols, kwargs))
            return {
                "600519.SH": pd.DataFrame(
                    [
                        {
                            "date": "2025-01-02",
                            "open": 10,
                            "high": 11,
                            "low": 9,
                            "close": 10.5,
                            "volume": 123,
                            "amount": 129150,
                        }
                    ]
                )
            }

    provider = TickFlowFreeProvider(client=SimpleNamespace(klines=_Klines()))
    result = provider.fetch_daily_bars(
        DailyBarsRequest(("600519.SH",), date(2025, 1, 1), date(2025, 1, 3), Adjustment.RAW)
    )

    assert calls[0][0] == ["600519.SH"]
    assert calls[0][1]["adjust"] == "none"
    assert calls[0][1]["count"] == 10_000
    assert result.data["600519.SH"][0].volume == 12300
    assert result.data["600519.SH"][0].amount == 129150
    assert result.data["600519.SH"][0].adjustment is Adjustment.RAW


def test_tickflow_daily_uses_one_sdk_batch_call_for_multiple_symbols_with_explicit_limits():
    calls = []
    symbols = ("600519.SH", "000001.SZ", "600000.SH")

    class _Klines:
        def batch(self, requested_symbols, **kwargs):
            calls.append((requested_symbols, kwargs))
            return {
                symbol: pd.DataFrame(
                    [
                        {
                            "date": "2025-01-02",
                            "open": 10,
                            "high": 11,
                            "low": 9,
                            "close": 10.5,
                            "volume": 123,
                            "amount": 129150,
                        }
                    ]
                )
                for symbol in requested_symbols
            }

    provider = TickFlowFreeProvider(
        client=SimpleNamespace(klines=_Klines()),
        batch_size=80,
        max_workers=3,
    )
    result = provider.fetch_daily_bars(DailyBarsRequest(symbols, date(2025, 1, 1), date(2025, 1, 3), Adjustment.RAW))

    assert len(calls) == 1
    assert calls[0][0] == list(symbols)
    assert calls[0][1]["batch_size"] == 80
    assert calls[0][1]["max_workers"] == 3
    assert set(result.data) == set(symbols)


def test_tickflow_batch_configuration_defaults_and_validation():
    config = DataProviderConfig()
    assert config.market_data_tickflow_batch_size == 100
    assert config.market_data_tickflow_max_concurrency == 5
    configured = (
        build_default_registry(
            DataProviderConfig(
                market_data_tickflow_batch_size=40,
                market_data_tickflow_max_concurrency=2,
            )
        )
        .get("tickflow")
        .provider
    )
    assert configured.batch_size == 40
    assert configured.max_workers == 2
    with pytest.raises(ValueError, match="between 1 and 100"):
        TickFlowFreeProvider(batch_size=101)
    with pytest.raises(ValueError, match="at least 1"):
        TickFlowFreeProvider(max_workers=0)


def test_tickflow_derives_daily_factors_from_consistent_raw_and_forward_ohlc():
    calls = []

    class _Klines:
        def batch(self, symbols, **kwargs):
            calls.append(kwargs)
            multiplier = 0.8 if kwargs["adjust"] == "forward" else 1.0
            return {
                "510300.SH": pd.DataFrame(
                    [
                        {
                            "date": "2025-01-02",
                            "open": 10 * multiplier,
                            "high": 11 * multiplier,
                            "low": 9 * multiplier,
                            "close": 10.5 * multiplier,
                            "volume": 123,
                            "amount": 129150,
                        }
                    ]
                )
            }

    provider = TickFlowFreeProvider(client=SimpleNamespace(klines=_Klines()))
    result = provider.get_adjustment_factors(AdjustmentRequest(("510300.SH",), date(2025, 1, 1), date(2025, 1, 3)))

    assert [call["adjust"] for call in calls] == ["none", "forward"]
    assert result.providers_used == {"510300.SH": "tickflow"}
    assert result.factors["510300.SH"][0].trade_date == date(2025, 1, 2)
    assert result.factors["510300.SH"][0].factor == pytest.approx(0.8)


def test_tickflow_rejects_inconsistent_ohlc_adjustment_ratios():
    class _Klines:
        def batch(self, symbols, **kwargs):
            values = {"open": 10, "high": 11, "low": 9, "close": 10.5}
            if kwargs["adjust"] == "forward":
                values = {"open": 8, "high": 9.9, "low": 7.2, "close": 8.4}
            return {"510300.SH": pd.DataFrame([{"date": "2025-01-02", **values, "volume": 123, "amount": 129150}])}

    provider = TickFlowFreeProvider(client=SimpleNamespace(klines=_Klines()))
    result = provider.get_adjustment_factors(AdjustmentRequest(("510300.SH",), date(2025, 1, 1), date(2025, 1, 3)))

    assert "inconsistent OHLC adjustment ratios" in result.failed_symbols["510300.SH"]


def test_adjustment_router_falls_back_to_tickflow_after_akshare_failure():
    trade_date = date(2025, 1, 2)

    class _AdjustmentProvider:
        def __init__(self, result):
            self.result = result
            self.requests = []

        def get_adjustment_factors(self, request):
            self.requests.append(request)
            return self.result

    akshare = _AdjustmentProvider(
        AdjustmentResult(failed_symbols={"510300.SH": "ETF factor response has four columns"})
    )
    tickflow = _AdjustmentProvider(
        AdjustmentResult(
            factors={"510300.SH": [AdjustmentFactor("510300.SH", trade_date, 0.8, "tickflow")]},
            providers_used={"510300.SH": "tickflow"},
        )
    )
    registry = ProviderRegistry()
    registry.register("akshare", akshare, capabilities={ADJUSTMENT_FACTORS})
    registry.register("tickflow", tickflow, capabilities={ADJUSTMENT_FACTORS})

    result = MarketDataService(registry).get_adjustment_factors(
        ["510300.SH"], date(2025, 1, 1), date(2025, 1, 3), providers=["akshare", "tickflow"]
    )

    assert result.providers_used == {"510300.SH": "tickflow"}
    assert result.factors["510300.SH"][0].factor == pytest.approx(0.8)
    assert tickflow.requests[0].symbols == ("510300.SH",)


def test_sync_persists_raw_bars_without_priority_or_estimated_amount():
    bar = _bar("600000.SH", "tickflow", amount=None)
    routed = BatchBarResult(data={"600000.SH": [bar]}, providers_used={"600000.SH": "tickflow"})
    market_data = SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed)
    stock_repository = SimpleNamespace(
        upsert_daily=lambda symbol_id, rows, source: SimpleNamespace(inserted_rows=1, updated_rows=0)
    )
    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = "CN"
    service.market_data = market_data
    service.stock_repository = stock_repository

    result = service._sync_daily(SimpleNamespace(id=1, code="600000.SH"), [date(2025, 1, 2)])

    assert result.status == "success"
    assert result.missing_amount is True
    assert result.providers == ["tickflow"]


def test_sync_treats_zero_amount_as_missing_vwap():
    bar = _bar("AAPL.US", "tickflow", amount=0)
    routed = BatchBarResult(data={"AAPL.US": [bar]}, providers_used={"AAPL.US": "tickflow"})
    persisted = []
    market_data = SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed)
    stock_repository = SimpleNamespace(
        upsert_daily=lambda symbol_id, rows, source: (
            persisted.extend(rows) or SimpleNamespace(inserted_rows=1, updated_rows=0)
        )
    )
    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = "US"
    service.market_data = market_data
    service.stock_repository = stock_repository

    result = service._sync_daily(SimpleNamespace(id=1, code="AAPL.US"), [date(2025, 1, 2)])

    assert result.status == "success"
    assert result.vwap_qualities == {"missing"}
    assert persisted[0]["amount"] == 0
    assert persisted[0]["vwap"] is None
    assert persisted[0]["vwap_source"] is None
    assert persisted[0]["vwap_quality"] == "missing"


class _DailyUpsertRepository:
    def __init__(self) -> None:
        self.persisted: dict[int, tuple[list[dict], str]] = {}

    def upsert_daily(self, symbol_id, rows, source):
        self.persisted[symbol_id] = (rows, source)
        return SimpleNamespace(inserted_rows=len(rows), updated_rows=0)


def _batch_sync_service(market_data, market="CN"):
    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = market
    service.market_data = market_data
    service.stock_repository = _DailyUpsertRepository()
    return service


def _bar_on(symbol: str, provider: str, trade_date: date, *, amount=1050) -> MarketBar:
    return replace(_bar(symbol, provider, amount=amount), trade_date=trade_date)


def test_cn_daily_batches_ten_symbols_with_same_window_in_one_service_call():
    symbols = [SimpleNamespace(id=index, code=f"600{index:03d}.SH") for index in range(10)]
    requested_days = [date(2025, 1, 2), date(2025, 1, 3)]
    tickflow = _DailyProvider(
        "tickflow",
        {
            symbol.code: [_bar_on(symbol.code, "tickflow", day) for day in requested_days]
            for symbol in symbols
        },
    )
    registry = ProviderRegistry()
    registry.register("tickflow", tickflow, capabilities={DAILY_BARS})
    service = _batch_sync_service(MarketDataService(registry))
    results = service._sync_daily_batch_groups(
        symbols,
        {symbol.code: requested_days for symbol in symbols},
    )

    assert len(tickflow.requests) == 1
    assert tickflow.requests[0].symbols == tuple(symbol.code for symbol in symbols)
    assert all(result.status == "success" for result in results.values())
    assert len(service.stock_repository.persisted) == 10


def test_us_daily_batches_ten_symbols_with_same_window_in_one_service_call():
    symbols = [SimpleNamespace(id=index, code=f"US{index}.US") for index in range(10)]
    requested_days = [date(2025, 1, 2), date(2025, 1, 3)]
    calls = []

    def get_daily_bars(codes, start_date, end_date, *, adjustment):
        calls.append((list(codes), start_date, end_date, adjustment))
        return BatchBarResult(
            data={code: [_bar_on(code, "yfinance", day) for day in requested_days] for code in codes},
            providers_used={code: "yfinance" for code in codes},
        )

    service = _batch_sync_service(SimpleNamespace(get_daily_bars=get_daily_bars), market="US")
    results = service._sync_daily_batch_groups(
        symbols,
        {symbol.code: requested_days for symbol in symbols},
    )

    assert len(calls) == 1
    assert calls[0][0] == [symbol.code for symbol in symbols]
    assert all(result.status == "success" for result in results.values())
    assert all(result.providers == ["yfinance"] for result in results.values())
    assert len(service.stock_repository.persisted) == 10


def test_us_adjustments_batch_ten_symbols_with_same_window_in_one_service_call():
    symbols = [SimpleNamespace(id=index, code=f"US{index}.US") for index in range(10)]
    requested_days = [date(2025, 1, 2), date(2025, 1, 3)]
    calls = []
    routed = AdjustmentResult()

    def get_adjustment_factors(codes, start_date, end_date):
        calls.append((list(codes), start_date, end_date))
        return routed

    service = _batch_sync_service(
        SimpleNamespace(get_adjustment_factors=get_adjustment_factors),
        market="US",
    )
    received = []

    def sync_adjustment(symbol, days, full_days, *, force_full_factor_window, routed):
        received.append((symbol.code, list(days), force_full_factor_window, routed))
        return SyncAdjustmentResult("success", provider="yfinance")

    service._sync_adjustment = sync_adjustment
    results = service._sync_adjustment_batch_groups(
        symbols,
        {symbol.code: requested_days for symbol in symbols},
        requested_days,
        {symbol.code: True for symbol in symbols},
    )

    assert len(calls) == 1
    assert calls[0][0] == [symbol.code for symbol in symbols]
    assert [item[0] for item in received] == [symbol.code for symbol in symbols]
    assert all(item[3] is routed for item in received)
    assert all(result.provider == "yfinance" for result in results.values())


def test_cn_daily_groups_initial_and_incremental_windows_into_two_calls():
    symbols = [SimpleNamespace(id=index, code=f"000{index:03d}.SZ") for index in range(10)]
    refresh_days = [date(2025, 1, 2), date(2025, 1, 3)]
    initial_days = [date(2020, 1, 2), date(2025, 1, 3)]
    days_by_code = {symbol.code: refresh_days if index < 8 else initial_days for index, symbol in enumerate(symbols)}
    calls = []

    def get_daily_bars(codes, start_date, end_date, *, adjustment):
        calls.append((tuple(codes), start_date, end_date))
        requested = refresh_days if start_date == refresh_days[0] else initial_days
        return BatchBarResult(
            data={code: [_bar_on(code, "tickflow", day) for day in requested] for code in codes},
            providers_used={code: "tickflow" for code in codes},
        )

    service = _batch_sync_service(SimpleNamespace(get_daily_bars=get_daily_bars))
    results = service._sync_daily_batch_groups(symbols, days_by_code)

    assert len(calls) == 2
    assert sorted(len(call[0]) for call in calls) == [2, 8]
    assert all(result.status == "success" for result in results.values())


def test_cn_daily_batch_preserves_per_symbol_router_fallback_and_provider_attribution():
    trade_date = date(2025, 1, 2)

    class _PartialTickFlow(_DailyProvider):
        def fetch_daily_bars(self, request):
            result = super().fetch_daily_bars(request)
            result.missing_symbols = [symbol for symbol in result.missing_symbols if symbol != "000002.SZ"]
            result.failed_symbols["000002.SZ"] = "timeout"
            return result

    first = _PartialTickFlow(
        "tickflow",
        {
            "600000.SH": [_bar_on("600000.SH", "tickflow", trade_date)],
            "000001.SZ": [_bar_on("000001.SZ", "tickflow", trade_date)],
        },
    )
    fallback = _DailyProvider(
        "akshare",
        {"000002.SZ": [_bar_on("000002.SZ", "akshare", trade_date)]},
    )
    registry = ProviderRegistry()
    registry.register("tickflow", first, capabilities={DAILY_BARS})
    registry.register("akshare", fallback, capabilities={DAILY_BARS})
    market_data = MarketDataService(registry)
    symbols = [
        SimpleNamespace(id=1, code="600000.SH"),
        SimpleNamespace(id=2, code="000001.SZ"),
        SimpleNamespace(id=3, code="000002.SZ"),
    ]
    service = _batch_sync_service(market_data)

    results = service._sync_daily_batch_groups(
        symbols,
        {symbol.code: [trade_date] for symbol in symbols},
    )

    assert len(first.requests) == 1
    assert first.requests[0].symbols == tuple(symbol.code for symbol in symbols)
    assert fallback.requests[0].symbols == ("000002.SZ",)
    assert results["600000.SH"].providers == ["tickflow"]
    assert results["000001.SZ"].providers == ["tickflow"]
    assert results["000002.SZ"].providers == ["akshare"]
    assert all(result.status == "success" for result in results.values())
    service.sync_mode = "incremental"
    service.unsupported_symbols = []
    summary = service._summarize(
        [SymbolResult(symbol.code, results[symbol.code], SyncAdjustmentResult("success")) for symbol in symbols],
        len(symbols),
    )
    assert summary["success_symbols"] == 3
    assert summary["failed_symbols"] == 0
    assert summary["provider_counts"] == {"tickflow": 2, "akshare": 1}


def test_cn_daily_batch_computes_missing_days_and_isolates_symbol_errors():
    first_day = date(2025, 1, 2)
    second_day = date(2025, 1, 3)
    symbols = [
        SimpleNamespace(id=1, code="600000.SH"),
        SimpleNamespace(id=2, code="000001.SZ"),
        SimpleNamespace(id=3, code="000002.SZ"),
    ]
    routed = BatchBarResult(
        data={
            "600000.SH": [
                _bar_on("600000.SH", "tickflow", first_day),
                _bar_on("600000.SH", "tickflow", second_day),
            ],
            "000001.SZ": [_bar_on("000001.SZ", "akshare", first_day)],
        },
        providers_used={"600000.SH": "tickflow", "000001.SZ": "akshare"},
        failed_symbols={"000002.SZ": "tickflow: timeout; akshare: empty"},
    )
    service = _batch_sync_service(SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed))

    results = service._sync_daily_batch_groups(
        symbols,
        {symbol.code: [first_day, second_day] for symbol in symbols},
    )

    assert results["600000.SH"].status == "success"
    assert results["600000.SH"].fallback_reasons == []
    assert results["000001.SZ"].status == "partial"
    assert results["000001.SZ"].reason == "missing_trading_days=1"
    assert results["000001.SZ"].fallback_reasons == []
    assert results["000002.SZ"].status == "failed"
    assert results["000002.SZ"].fallback_reasons == ["tickflow: timeout; akshare: empty"]


def test_sync_refreshes_instrument_names_in_one_remote_batch():
    calls = []
    upserts = []
    symbols = [
        SimpleNamespace(
            code="600000.SH",
            enabled=True,
            sync_daily=True,
            sync_minute=False,
        ),
        SimpleNamespace(
            code="000001.SZ",
            enabled=True,
            sync_daily=True,
            sync_minute=True,
        ),
    ]

    def get_instrument_info(codes, *, providers):
        calls.append((list(codes), tuple(providers)))
        return BatchInstrumentResult(
            data={
                "600000.SH": InstrumentInfo(
                    symbol="600000.SH",
                    market=Market.CN,
                    name="浦发银行",
                    provider="tickflow",
                    currency="CNY",
                    exchange="SH",
                    instrument_type="stock",
                    lot_size=100,
                ),
                "000001.SZ": InstrumentInfo(
                    symbol="000001.SZ",
                    market=Market.CN,
                    name="平安银行",
                    provider="tickflow",
                    currency="CNY",
                    exchange="SZ",
                    instrument_type="stock",
                    lot_size=100,
                ),
            }
        )

    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = "CN"
    service.market_data = SimpleNamespace(
        registry=SimpleNamespace(names=lambda: ("database", "tickflow", "longbridge", "akshare")),
        get_instrument_info=get_instrument_info,
    )
    service.symbol_repository = SimpleNamespace(
        upsert_symbols=lambda records, overwrite_runtime_flags: upserts.append((records, overwrite_runtime_flags))
    )
    service.instrument_names_refreshed = 0
    service.instrument_name_failures = {}

    service._refresh_instrument_names(symbols)

    assert calls == [
        (
            ["600000.SH", "000001.SZ"],
            ("tickflow", "akshare"),
        )
    ]
    assert [record["name"] for record in upserts[0][0]] == ["浦发银行", "平安银行"]
    assert upserts[0][1] is False
    assert service.instrument_names_refreshed == 2


def test_us_sync_instrument_name_refresh_does_not_route_to_longbridge():
    calls = []
    symbol = SimpleNamespace(
        code="AAPL.US",
        enabled=True,
        sync_daily=True,
        sync_minute=False,
    )

    def get_instrument_info(codes, *, providers):
        calls.append((list(codes), tuple(providers)))
        return BatchInstrumentResult(missing_symbols=list(codes))

    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = "US"
    service.market_data = SimpleNamespace(
        registry=SimpleNamespace(names=lambda: ("database", "tickflow", "longbridge", "yfinance", "akshare")),
        get_instrument_info=get_instrument_info,
    )
    service.symbol_repository = SimpleNamespace(upsert_symbols=lambda *args, **kwargs: None)
    service.instrument_names_refreshed = 0
    service.instrument_name_failures = {}

    service._refresh_instrument_names([symbol])

    assert calls == [(["AAPL.US"], ("tickflow", "akshare"))]
    assert "longbridge" not in calls[0][1]


def test_cn_daily_default_chain_uses_efinance_snapshot_for_latest_day():
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    tickflow = _DailyProvider("tickflow", {"600000.SH": [_bar("600000.SH", "tickflow")]})
    tickflow.values["600000.SH"][0] = MarketBar(
        **{
            **tickflow.values["600000.SH"][0].to_dict(),
            "trade_date": today - timedelta(days=1),
            "market": Market.CN,
            "adjustment": Adjustment.RAW,
        }
    )
    empty_akshare = _DailyProvider("akshare", {})
    empty_pytdx = _DailyProvider("pytdx", {})

    class _Snapshot:
        def fetch_market_snapshot(self, market):
            quote = MarketQuote(
                symbol="600000.SH",
                market=Market.CN,
                provider="efinance",
                currency="CNY",
                price=10.8,
                open_price=10.1,
                high=11,
                low=10,
                volume=1000,
                amount=10800,
                quote_time=datetime.now(ZoneInfo("Asia/Shanghai")),
            )
            return BatchQuoteResult(data={"600000.SH": quote})

    registry = ProviderRegistry()
    registry.register("tickflow", tickflow, capabilities={DAILY_BARS})
    registry.register("akshare", empty_akshare, capabilities={DAILY_BARS})
    registry.register("pytdx", empty_pytdx, capabilities={DAILY_BARS})
    registry.register("efinance", _Snapshot(), capabilities={LATEST_MARKET_SNAPSHOT})

    result = MarketDataService(registry).get_daily_bars(
        ["600000.SH"], today - timedelta(days=2), today, adjustment="raw"
    )

    assert [bar.trade_date for bar in result.data["600000.SH"]] == [today - timedelta(days=1), today]
    assert result.data["600000.SH"][-1].provider == "efinance"
    assert result.providers_used["600000.SH"] == "efinance"

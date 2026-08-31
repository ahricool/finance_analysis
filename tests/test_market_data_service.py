from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.config import provider_order
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
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.market_data.service import build_default_registry
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
                    [{"date": "2025-01-02", "open": 10, "high": 11, "low": 9, "close": 10.5,
                      "volume": 123, "amount": 129150}]
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
                    provider="longbridge",
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
        upsert_symbols=lambda records, overwrite_runtime_flags: upserts.append(
            (records, overwrite_runtime_flags)
        )
    )
    service.instrument_names_refreshed = 0
    service.instrument_name_failures = {}

    service._refresh_instrument_names(symbols)

    assert calls == [
        (
            ["600000.SH", "000001.SZ"],
            ("tickflow", "longbridge", "akshare"),
        )
    ]
    assert [record["name"] for record in upserts[0][0]] == ["浦发银行", "平安银行"]
    assert upserts[0][1] is False
    assert service.instrument_names_refreshed == 2


def test_cn_daily_default_chain_uses_efinance_snapshot_for_latest_day():
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    tickflow = _DailyProvider("tickflow", {"600000.SH": [_bar("600000.SH", "tickflow")]})
    tickflow.values["600000.SH"][0] = MarketBar(
        **{**tickflow.values["600000.SH"][0].to_dict(), "trade_date": today - timedelta(days=1),
           "market": Market.CN, "adjustment": Adjustment.RAW}
    )
    empty_akshare = _DailyProvider("akshare", {})
    empty_pytdx = _DailyProvider("pytdx", {})

    class _Snapshot:
        def fetch_market_snapshot(self, market):
            quote = MarketQuote(
                symbol="600000.SH", market=Market.CN, provider="efinance", currency="CNY",
                price=10.8, open_price=10.1, high=11, low=10, volume=1000, amount=10800,
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

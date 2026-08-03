from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.config import provider_order
from finance_analysis.integrations.market_data.models import (
    Adjustment,
    BatchBarResult,
    BatchQuoteResult,
    DailyBarsRequest,
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


def test_default_registry_excludes_unsupported_efinance_daily_and_tickflow_factors():
    registry = build_default_registry()
    assert DAILY_BARS not in registry.capabilities("efinance")
    assert ADJUSTMENT_FACTORS not in registry.capabilities("tickflow")


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

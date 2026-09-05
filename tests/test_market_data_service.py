from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from finance_analysis.database.repositories.stock import StockRepository
from finance_analysis.integrations.market_data.config import DataProviderConfig, provider_order
from finance_analysis.integrations.market_data.models import (
    Adjustment,
    BatchBarResult,
    DailyBarsRequest,
    Market,
    MarketBar,
)
from finance_analysis.integrations.market_data.providers.akshare import AkShareProvider
from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider
from finance_analysis.integrations.market_data.registry import (
    DAILY_BARS,
    MINUTE_BARS,
    ProviderConfigurationError,
    ProviderRegistry,
)
from finance_analysis.integrations.market_data.service import MarketDataService, build_default_registry
from finance_analysis.tasks.celery.jobs.market_data_sync.models import DailyResult, SymbolResult
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
        adjustment=Adjustment.FORWARD,
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
        adjustment="forward",
        providers=["first", "second"],
        source_policy="remote_only",
    )

    assert result.providers_used == {"600000.SH": "first", "000001.SZ": "second"}
    assert second.requests[0].symbols == ("000001.SZ",)


def test_amount_is_not_estimated_when_provider_omits_it():
    provider = _DailyProvider("daily", {"600000.SH": [_bar("600000.SH", "daily")]})
    registry = ProviderRegistry()
    registry.register("daily", provider, capabilities={DAILY_BARS})
    result = MarketDataService(registry).get_daily_bars(
        ["600000.SH"],
        date(2025, 1, 1),
        date(2025, 1, 3),
        adjustment="forward",
        providers=["daily"],
        source_policy="remote_only",
    )
    bar = result.data["600000.SH"][0]
    assert bar.amount is None
    assert bar.amount_estimated is False


def test_daily_service_rejects_raw_prices_before_provider_io():
    provider = _DailyProvider("daily", {"600000.SH": [_bar("600000.SH", "daily")]})
    registry = ProviderRegistry()
    registry.register("daily", provider, capabilities={DAILY_BARS})

    with pytest.raises(ValueError, match="only as forward-adjusted"):
        MarketDataService(registry).get_daily_bars(
            ["600000.SH"], date(2025, 1, 1), date(2025, 1, 3), adjustment="raw", providers=["daily"]
        )

    assert provider.requests == []


def test_router_rejects_raw_provider_output_and_falls_back_to_adjusted_provider():
    raw_bar = replace(_bar("600000.SH", "raw"), adjustment=Adjustment.RAW)
    raw = _DailyProvider("raw", {"600000.SH": [raw_bar]})
    adjusted = _DailyProvider("adjusted", {"600000.SH": [_bar("600000.SH", "adjusted")]})
    registry = ProviderRegistry()
    registry.register("raw", raw, capabilities={DAILY_BARS})
    registry.register("adjusted", adjusted, capabilities={DAILY_BARS})

    result = MarketDataService(registry).get_daily_bars(
        ["600000.SH"],
        date(2025, 1, 1),
        date(2025, 1, 3),
        adjustment="forward",
        providers=["raw", "adjusted"],
        source_policy="remote_only",
    )

    assert result.providers_used == {"600000.SH": "adjusted"}
    assert result.data["600000.SH"][0].adjustment is Adjustment.FORWARD


class _PolicyInstrumentRepository:
    def __init__(self, code="600000.SH"):
        self.instrument = SimpleNamespace(id=7, code=code, market="CN")

    def get_by_code(self, code):
        return self.instrument if code == self.instrument.code else None


class _PolicyStockRepository:
    def __init__(self, rows=()):
        self.rows = {row.date: row for row in rows}
        self.upserts = []

    def has_daily_data(self, instrument_id):
        return bool(self.rows)

    def latest_daily_dates(self, instrument_ids):
        return {instrument_id: max(self.rows) for instrument_id in instrument_ids} if self.rows else {}

    def get_daily_ranges(self, codes, start_date, end_date):
        return {code: [self.rows[day] for day in sorted(self.rows) if start_date <= day <= end_date] for code in codes}

    def get_range(self, code, start_date, end_date):
        del code
        return [self.rows[day] for day in sorted(self.rows) if start_date <= day <= end_date]

    def upsert_daily(self, instrument_id, rows, source):
        self.upserts.append((instrument_id, rows, source))
        return SimpleNamespace(inserted_rows=len(rows), updated_rows=0)


def _stored_policy_row(day):
    instrument = SimpleNamespace(id=7, code="600000.SH", market="CN")
    return SimpleNamespace(
        instrument=instrument,
        date=day,
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume=100,
        amount=1000,
    )


@pytest.mark.parametrize(
    "local_days",
    [
        [date(2025, 1, 2), date(2025, 1, 6)],  # suspension gap
        [date(2025, 1, 6)],  # newly listed
        [date(2019, 1, 2)],  # any history, even outside the requested range
        [],
    ],
)
def test_daily_source_policies_are_read_only_and_use_any_local_history(local_days):
    provider = _DailyProvider("daily", {"600000.SH": [_bar_on("600000.SH", "daily", date(2025, 1, 6))]})
    registry = ProviderRegistry()
    registry.register("daily", provider, capabilities={DAILY_BARS})
    stocks = _PolicyStockRepository([_stored_policy_row(day) for day in local_days])
    service = MarketDataService(registry, instrument_repository=_PolicyInstrumentRepository(), stock_repository=stocks)
    args = (["600000.SH"], date(2020, 1, 1), date(2025, 1, 6))
    result = service.get_daily_bars(*args, adjustment="forward", providers=["daily"])
    assert len(provider.requests) == (0 if local_days else 1)
    assert stocks.upserts == []
    before = len(provider.requests)
    service.get_daily_bars(*args, adjustment="forward", source_policy="db_only")
    assert len(provider.requests) == before
    service.get_daily_bars(*args, adjustment="forward", providers=["daily"], source_policy="remote_only")
    assert len(provider.requests) == before + 1
    assert stocks.upserts == []
    if local_days == [date(2019, 1, 2)]:
        assert result.data == {}


def test_default_orders_are_explicit_and_not_integer_priorities():
    assert provider_order(Market.CN, DAILY_BARS) == ("tickflow", "akshare", "pytdx", "baostock", "yfinance")
    assert provider_order(Market.CN, DAILY_BARS)[0] == "tickflow"
    assert "longbridge" not in provider_order(Market.CN, DAILY_BARS)
    assert provider_order(Market.US, DAILY_BARS) == ("yfinance", "tickflow")
    assert provider_order(Market.US, DAILY_BARS)[0] == "yfinance"
    assert "longbridge" not in provider_order(Market.US, DAILY_BARS)
    assert "akshare" not in provider_order(Market.US, DAILY_BARS)
    assert provider_order(Market.CN, MINUTE_BARS) == ("streaming", "longbridge", "efinance", "pytdx", "akshare")


def test_default_registry_excludes_unsupported_efinance_daily():
    registry = build_default_registry()
    assert DAILY_BARS not in registry.capabilities("efinance")


def test_akshare_us_daily_is_not_a_configured_or_direct_fallback():
    provider = AkShareProvider(sleep_min=0, sleep_max=0)

    result = provider.fetch_daily_bars(
        DailyBarsRequest(("AAPL.US",), date(2025, 1, 1), date(2025, 1, 3), Adjustment.FORWARD)
    )

    assert result.data == {}
    assert "canonical CN/HK symbol" in result.failed_symbols["AAPL.US"]


def test_tickflow_free_uses_maximum_history_count_native_batch_forward_and_cn_lots_become_shares():
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
        DailyBarsRequest(("600519.SH",), date(2025, 1, 1), date(2025, 1, 3), Adjustment.FORWARD)
    )

    assert calls[0][0] == ["600519.SH"]
    assert calls[0][1]["adjust"] == "forward"
    assert calls[0][1]["count"] == 10_000
    assert result.data["600519.SH"][0].volume == 12300
    assert result.data["600519.SH"][0].amount == 129150
    assert result.data["600519.SH"][0].adjustment is Adjustment.FORWARD


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
    result = provider.fetch_daily_bars(
        DailyBarsRequest(symbols, date(2025, 1, 1), date(2025, 1, 3), Adjustment.FORWARD)
    )

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


def test_full_batch_keeps_failed_symbol_history_and_distinguishes_normal_empty():
    day = date(2025, 1, 2)
    symbols = [SimpleNamespace(id=i, code=code) for i, code in enumerate(("600000.SH", "600001.SH", "600002.SH"), 1)]

    class Klines:
        def batch(self, codes, **kwargs):
            assert len(codes) == 1  # still an HTTP-sized batch, isolated on failure
            if codes == ["600000.SH"]:
                raise TimeoutError("chunk failed")
            if codes == ["600002.SH"]:
                return {codes[0]: pd.DataFrame()}
            return {
                codes[0]: pd.DataFrame(
                    [
                        {
                            "date": day,
                            "open": 10,
                            "high": 11,
                            "low": 9,
                            "close": 10,
                            "volume": 100,
                        }
                    ]
                )
            }

    provider = TickFlowFreeProvider(client=SimpleNamespace(klines=Klines()), batch_size=1)
    fetched = provider.fetch_daily_bars(
        DailyBarsRequest(tuple(symbol.code for symbol in symbols), day, day, Adjustment.FORWARD)
    )
    assert set(fetched.request_errors) == {"600000.SH"}
    assert fetched.missing_symbols == ["600002.SH"]
    original = {day: {"date": day, "close": 20}}
    sync = _batch_sync_service(SimpleNamespace(get_daily_bars=lambda *args, **kwargs: fetched))
    sync.sync_mode = "full"
    sync.stock_repository = _DailyUpsertRepository(histories={symbol.id: dict(original) for symbol in symbols})
    results = sync._sync_daily_batch_groups(symbols, {symbol.code: [day] for symbol in symbols}, full_days=[day])
    assert results["600000.SH"].status == "failed"
    assert results["600001.SH"].status == results["600002.SH"].status == "success"
    assert sync.stock_repository.replaced_symbol_ids == [2]
    assert sync.stock_repository.upserted_symbol_ids == []
    assert sync.stock_repository.histories[1] == sync.stock_repository.histories[3] == original


def test_yfinance_logged_symbol_exception_survives_retry(monkeypatch):
    import logging
    import yfinance
    from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider

    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            logging.getLogger("yfinance").error("['AAPL']: TimeoutError('request failed')")
            return pd.DataFrame()
        return pd.DataFrame([{"Date": date(2025, 1, 2), "Open": 10, "High": 11, "Low": 9, "Close": 10, "Volume": 100}])

    monkeypatch.setattr(yfinance, "download", download)
    result = YFinanceProvider(max_retries=1).fetch_daily_bars(
        DailyBarsRequest(("AAPL.US",), date(2025, 1, 1), date(2025, 1, 3), Adjustment.FORWARD)
    )
    assert "AAPL.US" in result.data
    assert "TimeoutError" in result.request_errors["AAPL.US"]


def test_yfinance_batch_and_retry_configuration_reaches_default_registry():
    configured = (
        build_default_registry(
            DataProviderConfig(
                market_data_yfinance_batch_size=25,
                market_data_yfinance_max_concurrency=2,
                market_data_yfinance_max_retries=4,
            )
        )
        .get("yfinance")
        .provider
    )

    assert configured.batch_size == 25
    assert configured.max_workers == 2
    assert configured.max_retries == 4


def test_sync_persists_only_provider_daily_fields_with_nullable_amount():
    bar = _bar("600000.SH", "tickflow", amount=None)
    routed = BatchBarResult(data={"600000.SH": [bar]}, providers_used={"600000.SH": "tickflow"})
    market_data = SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed)
    persisted = []
    stock_repository = SimpleNamespace(
        upsert_daily=lambda instrument_id, rows, source: (
            persisted.extend(rows) or SimpleNamespace(inserted_rows=1, updated_rows=0)
        )
    )
    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = "CN"
    service.market_data = market_data
    service.stock_repository = stock_repository

    result = service._sync_daily(SimpleNamespace(id=1, code="600000.SH"), [date(2025, 1, 2)])

    assert result.status == "success"
    assert result.missing_amount is True
    assert result.providers == ["tickflow"]
    assert set(persisted[0]) == {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "data_source",
    }
    assert persisted[0]["date"] == date(2025, 1, 2)
    assert persisted[0]["open"] == 10
    assert persisted[0]["high"] == 11
    assert persisted[0]["low"] == 9
    assert persisted[0]["close"] == 10.5
    assert persisted[0]["volume"] == 100
    assert persisted[0]["amount"] is None
    assert persisted[0]["data_source"] == "tickflow"


def test_stock_daily_records_preserve_per_row_provider_for_gap_patches():
    records = StockRepository._daily_records(
        1,
        [
            {
                "date": date(2025, 1, 2),
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "amount": None,
                "data_source": "tickflow",
            }
        ],
        "mixed",
    )

    assert records[0]["data_source"] == "tickflow"


def test_sync_preserves_provider_amount_without_persisting_derived_price_metadata():
    bar = _bar("AAPL.US", "yfinance", amount=10_500)
    routed = BatchBarResult(data={"AAPL.US": [bar]}, providers_used={"AAPL.US": "yfinance"})
    persisted = []
    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = "US"
    service.stock_repository = SimpleNamespace(
        upsert_daily=lambda instrument_id, rows, source: (
            persisted.extend(rows) or SimpleNamespace(inserted_rows=1, updated_rows=0)
        )
    )

    result = service._persist_daily_result(SimpleNamespace(id=1, code="AAPL.US"), [bar.trade_date], routed)

    assert result.status == "success"
    assert persisted[0]["amount"] == 10_500
    assert "vwap" not in persisted[0]


def test_sync_preserves_zero_provider_amount_without_derived_metadata():
    bar = _bar("AAPL.US", "tickflow", amount=0)
    routed = BatchBarResult(data={"AAPL.US": [bar]}, providers_used={"AAPL.US": "tickflow"})
    persisted = []
    market_data = SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed)
    stock_repository = SimpleNamespace(
        upsert_daily=lambda instrument_id, rows, source: (
            persisted.extend(rows) or SimpleNamespace(inserted_rows=1, updated_rows=0)
        )
    )
    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = "US"
    service.market_data = market_data
    service.stock_repository = stock_repository

    result = service._sync_daily(SimpleNamespace(id=1, code="AAPL.US"), [date(2025, 1, 2)])

    assert result.status == "success"
    assert persisted[0]["amount"] == 0
    assert "vwap" not in persisted[0]


class _DailyUpsertRepository:
    def __init__(self, stored_closes=None, histories=None) -> None:
        self.persisted: dict[int, tuple[list[dict], str]] = {}
        self.stored_closes = stored_closes or {}
        self.histories = {instrument_id: dict(rows) for instrument_id, rows in (histories or {}).items()}
        self.upserted_symbol_ids = []
        self.replaced_symbol_ids = []

    def upsert_daily(self, instrument_id, rows, source):
        self.upserted_symbol_ids.append(instrument_id)
        self.persisted[instrument_id] = (rows, source)
        history = self.histories.setdefault(instrument_id, {})
        history.update({row["date"]: row for row in rows})
        return SimpleNamespace(inserted_rows=len(rows), updated_rows=0)

    def replace_daily_history(self, instrument_id, rows, source):
        self.replaced_symbol_ids.append(instrument_id)
        self.persisted[instrument_id] = (rows, source)
        deleted_rows = len(self.histories.get(instrument_id, {}))
        self.histories[instrument_id] = {row["date"]: row for row in rows}
        return SimpleNamespace(inserted_rows=len(rows), updated_rows=0, deleted_rows=deleted_rows)

    def daily_closes(self, instrument_id, start_date, end_date):
        return {
            day: close
            for day, close in self.stored_closes.get(instrument_id, {}).items()
            if start_date <= day <= end_date
        }

    def daily_dates(self, instrument_id, start_date, end_date):
        return {day for day in self.histories.get(instrument_id, {}) if start_date <= day <= end_date}


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
        {symbol.code: [_bar_on(symbol.code, "tickflow", day) for day in requested_days] for symbol in symbols},
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
    assert service.stock_repository.replaced_symbol_ids == []


def test_us_daily_batches_ten_symbols_with_same_window_in_one_service_call():
    symbols = [SimpleNamespace(id=index, code=f"US{index}.US") for index in range(10)]
    requested_days = [date(2025, 1, 2), date(2025, 1, 3)]
    calls = []

    def get_daily_bars(codes, start_date, end_date, *, adjustment, source_policy=None):
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


def test_us_daily_retries_observed_date_gaps_then_patches_with_tickflow():
    first_day = date(2025, 1, 2)
    second_day = date(2025, 1, 3)
    symbols = [SimpleNamespace(id=1, code="AAPL.US"), SimpleNamespace(id=2, code="MSFT.US")]
    calls = []

    def get_daily_bars(codes, start_date, end_date, *, adjustment, providers=None, source_policy=None):
        calls.append((tuple(codes), start_date, end_date, providers))
        if providers == ("tickflow",):
            return BatchBarResult(
                data={"MSFT.US": [_bar_on("MSFT.US", "tickflow", second_day)]},
                providers_used={"MSFT.US": "tickflow"},
            )
        if providers == ("yfinance",):
            return BatchBarResult(
                data={"MSFT.US": [_bar_on("MSFT.US", "yfinance", first_day)]},
                providers_used={"MSFT.US": "yfinance"},
            )
        return BatchBarResult(
            data={
                "AAPL.US": [
                    _bar_on("AAPL.US", "yfinance", first_day),
                    _bar_on("AAPL.US", "yfinance", second_day),
                ],
                "MSFT.US": [_bar_on("MSFT.US", "yfinance", first_day)],
            },
            providers_used={"AAPL.US": "yfinance", "MSFT.US": "yfinance"},
        )

    service = _batch_sync_service(SimpleNamespace(get_daily_bars=get_daily_bars), market="US")
    service.config = SimpleNamespace(market_data_yfinance_max_retries=2)
    results = service._sync_daily_batch_groups(
        symbols,
        {symbol.code: [first_day, second_day] for symbol in symbols},
    )

    assert [call[3] for call in calls] == [None, ("yfinance",), ("yfinance",), ("tickflow",)]
    assert results["AAPL.US"].providers == ["yfinance"]
    assert results["MSFT.US"].providers == ["yfinance", "tickflow"]
    assert results["MSFT.US"].status == "success"
    rows, source = service.stock_repository.persisted[2]
    assert source == "mixed"
    assert [(row["date"], row["data_source"]) for row in rows] == [
        (first_day, "yfinance"),
        (second_day, "tickflow"),
    ]


def test_cn_daily_groups_initial_and_incremental_windows_into_two_calls():
    symbols = [SimpleNamespace(id=index, code=f"000{index:03d}.SZ") for index in range(10)]
    refresh_days = [date(2025, 1, 2), date(2025, 1, 3)]
    initial_days = [date(2020, 1, 2), date(2025, 1, 3)]
    days_by_code = {symbol.code: refresh_days if index < 8 else initial_days for index, symbol in enumerate(symbols)}
    calls = []

    def get_daily_bars(codes, start_date, end_date, *, adjustment, source_policy=None):
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


def test_incremental_scale_change_upgrades_only_affected_symbol_to_full_refresh():
    symbol = SimpleNamespace(id=1, code="600000.SH")
    incremental_days = [date(2025, 1, day) for day in (2, 3, 6, 7)]
    full_days = [date(2020, 1, 2), *incremental_days]
    calls = []

    def get_daily_bars(codes, start_date, end_date, *, adjustment, source_policy=None):
        calls.append((list(codes), start_date, end_date, adjustment))
        days = full_days if start_date == full_days[0] else incremental_days
        closes = [90.0, 90.0, 90.0, 100.0] if days is incremental_days else [90.0] * len(days)
        return BatchBarResult(
            data={
                symbol.code: [
                    replace(_bar_on(symbol.code, "tickflow", day), close=close) for day, close in zip(days, closes)
                ]
            },
            providers_used={symbol.code: "tickflow"},
        )

    service = _batch_sync_service(SimpleNamespace(get_daily_bars=get_daily_bars))
    service.sync_mode = "incremental"
    old_day = date(2019, 1, 2)
    service.stock_repository = _DailyUpsertRepository(
        {symbol.id: {day: 100.0 for day in incremental_days}},
        {symbol.id: {day: {"date": day} for day in [old_day, *full_days]}},
    )

    result = service._sync_daily_batch_groups(
        [symbol],
        {symbol.code: incremental_days},
        full_days=full_days,
    )[symbol.code]

    assert len(calls) == 2
    assert calls[1][1:3] == (full_days[0], full_days[-1])
    assert result.automatic_full_refresh is True
    assert service.stock_repository.upserted_symbol_ids == []
    assert service.stock_repository.replaced_symbol_ids == [symbol.id]
    assert [row["date"] for row in service.stock_repository.persisted[symbol.id][0]] == full_days
    assert set(service.stock_repository.histories[symbol.id]) == set(full_days)


def test_incremental_ordinary_price_correction_does_not_trigger_full_refresh():
    symbol = SimpleNamespace(id=1, code="AAPL.US")
    incremental_days = [date(2025, 1, day) for day in (2, 3, 6, 7)]
    full_days = [date(2020, 1, 2), *incremental_days]
    calls = []
    corrected_closes = [99.0, 100.0, 100.0, 100.0]

    def get_daily_bars(codes, start_date, end_date, *, adjustment, source_policy=None):
        calls.append((list(codes), start_date, end_date, adjustment))
        return BatchBarResult(
            data={
                symbol.code: [
                    replace(_bar_on(symbol.code, "yfinance", day), close=close)
                    for day, close in zip(incremental_days, corrected_closes)
                ]
            },
            providers_used={symbol.code: "yfinance"},
        )

    service = _batch_sync_service(SimpleNamespace(get_daily_bars=get_daily_bars), market="US")
    service.sync_mode = "incremental"
    old_day = date(2020, 1, 2)
    service.stock_repository = _DailyUpsertRepository(
        {symbol.id: {day: 100.0 for day in incremental_days}},
        {symbol.id: {old_day: {"date": old_day}}},
    )

    result = service._sync_daily_batch_groups(
        [symbol],
        {symbol.code: incremental_days},
        full_days=full_days,
    )[symbol.code]

    assert len(calls) == 1
    assert result.automatic_full_refresh is False
    assert service.stock_repository.upserted_symbol_ids == [symbol.id]
    assert service.stock_repository.replaced_symbol_ids == []
    assert [row["date"] for row in service.stock_repository.persisted[symbol.id][0]] == incremental_days
    assert old_day in service.stock_repository.histories[symbol.id]


def test_automatic_full_request_error_preserves_existing_history():
    symbol = SimpleNamespace(id=1, code="600000.SH")
    full_days = [date(2024, 1, 1) + timedelta(days=offset) for offset in range(100)]
    incremental_days = full_days[-4:]
    returned_full_days = full_days[:10]
    original_history = {day: {"date": day} for day in full_days}

    def get_daily_bars(codes, start_date, end_date, *, adjustment, source_policy=None):
        days = returned_full_days if start_date == full_days[0] else incremental_days
        closes = [90.0] * len(days)
        return BatchBarResult(
            data={
                symbol.code: [
                    replace(_bar_on(symbol.code, "tickflow", day), close=close) for day, close in zip(days, closes)
                ]
            },
            providers_used={symbol.code: "tickflow"},
            request_errors={symbol.code: "HTTP 500"} if start_date == full_days[0] else {},
        )

    service = _batch_sync_service(SimpleNamespace(get_daily_bars=get_daily_bars))
    service.sync_mode = "incremental"
    service.stock_repository = _DailyUpsertRepository(
        {symbol.id: {day: 100.0 for day in incremental_days}},
        {symbol.id: original_history},
    )

    result = service._sync_daily_batch_groups(
        [symbol],
        {symbol.code: incremental_days},
        full_days=full_days,
    )[symbol.code]

    assert result.status == "failed"
    assert result.automatic_full_refresh is True
    assert "full_fetch_failed" in result.reason
    assert service.stock_repository.replaced_symbol_ids == []
    assert service.stock_repository.histories[symbol.id] == original_history


@pytest.mark.parametrize("failure", ["HTTP 400", "HTTP 404", "HTTP 429", "HTTP 500", "timeout", "SDK exception"])
def test_scheduled_full_request_error_preserves_existing_history(failure):
    symbol = SimpleNamespace(id=1, code="AAPL.US")
    full_days = [date(2024, 1, 1) + timedelta(days=offset) for offset in range(100)]
    returned_days = full_days[:20]
    original_history = {day: {"date": day} for day in full_days}
    routed = BatchBarResult(
        data={symbol.code: [_bar_on(symbol.code, "yfinance", day) for day in returned_days]},
        providers_used={symbol.code: "yfinance"},
        request_errors={symbol.code: failure},
    )
    service = _batch_sync_service(SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed), market="US")
    service.sync_mode = "full"
    service.stock_repository = _DailyUpsertRepository(histories={symbol.id: original_history})

    result = service._sync_daily_batch_groups(
        [symbol],
        {symbol.code: full_days},
        full_days=full_days,
    )[symbol.code]

    assert result.status == "failed"
    assert "full_fetch_failed" in result.reason
    assert service.stock_repository.replaced_symbol_ids == []
    assert service.stock_repository.histories[symbol.id] == original_history


def test_scheduled_full_accepts_existing_history_with_long_suspension_gaps():
    symbol = SimpleNamespace(id=1, code="600000.SH")
    full_days = [date(2024, 1, 1) + timedelta(days=offset) for offset in range(100)]
    valid_days = [day for index, day in enumerate(full_days) if index % 10]
    existing_history = {day: {"date": day} for day in valid_days}
    routed = BatchBarResult(
        data={symbol.code: [_bar_on(symbol.code, "tickflow", day) for day in valid_days]},
        providers_used={symbol.code: "tickflow"},
    )
    service = _batch_sync_service(SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed))
    service.sync_mode = "full"
    service.stock_repository = _DailyUpsertRepository(histories={symbol.id: existing_history})

    result = service._sync_daily_batch_groups(
        [symbol],
        {symbol.code: full_days},
        full_days=full_days,
    )[symbol.code]

    assert result.status == "success"
    assert result.reason == ""
    assert service.stock_repository.replaced_symbol_ids == [symbol.id]
    assert set(service.stock_repository.histories[symbol.id]) == set(valid_days)


def test_automatic_full_accepts_existing_history_with_long_suspension_gaps():
    symbol = SimpleNamespace(id=1, code="600000.SH")
    full_days = [date(2024, 1, 1) + timedelta(days=offset) for offset in range(100)]
    valid_days = [day for index, day in enumerate(full_days) if index % 10]
    incremental_days = valid_days[-4:]
    existing_history = {day: {"date": day} for day in valid_days}

    def get_daily_bars(codes, start_date, end_date, *, adjustment, source_policy=None):
        days = valid_days if start_date == full_days[0] else incremental_days
        return BatchBarResult(
            data={symbol.code: [replace(_bar_on(symbol.code, "tickflow", day), close=90.0) for day in days]},
            providers_used={symbol.code: "tickflow"},
        )

    service = _batch_sync_service(SimpleNamespace(get_daily_bars=get_daily_bars))
    service.sync_mode = "incremental"
    service.stock_repository = _DailyUpsertRepository(
        {symbol.id: {day: 100.0 for day in incremental_days}},
        {symbol.id: existing_history},
    )

    result = service._sync_daily_batch_groups(
        [symbol],
        {symbol.code: incremental_days},
        full_days=full_days,
    )[symbol.code]

    assert result.status == "success"
    assert result.automatic_full_refresh is True
    assert service.stock_repository.replaced_symbol_ids == [symbol.id]
    assert set(service.stock_repository.histories[symbol.id]) == set(valid_days)


def test_first_full_sync_accepts_contiguous_history_for_newly_listed_symbol():
    symbol = SimpleNamespace(id=1, code="NEW.US")
    full_days = [date(2024, 1, 1) + timedelta(days=offset) for offset in range(100)]
    listed_days = full_days[-20:]
    routed = BatchBarResult(
        data={symbol.code: [_bar_on(symbol.code, "yfinance", day) for day in listed_days]},
        providers_used={symbol.code: "yfinance"},
    )
    service = _batch_sync_service(SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed), market="US")
    service.sync_mode = "full"

    result = service._sync_daily_batch_groups(
        [symbol],
        {symbol.code: full_days},
        full_days=full_days,
    )[symbol.code]

    assert result.status == "success"
    assert service.stock_repository.replaced_symbol_ids == [symbol.id]
    assert set(service.stock_repository.histories[symbol.id]) == set(listed_days)


def test_full_replaces_successful_symbols_and_preserves_failed_symbol_history():
    successful = SimpleNamespace(id=1, code="600000.SH")
    failed = SimpleNamespace(id=2, code="000001.SZ")
    symbols = [successful, failed]
    full_days = [date(2020, 1, 2), date(2025, 1, 2)]
    successful_old_day = date(2018, 1, 2)
    failed_old_day = date(2019, 1, 2)

    routed = BatchBarResult(
        data={successful.code: [_bar_on(successful.code, "tickflow", day) for day in full_days]},
        providers_used={successful.code: "tickflow"},
        failed_symbols={failed.code: "tickflow: timeout"},
    )
    service = _batch_sync_service(SimpleNamespace(get_daily_bars=lambda *args, **kwargs: routed))
    service.sync_mode = "full"
    service.stock_repository = _DailyUpsertRepository(
        histories={
            successful.id: {
                successful_old_day: {"date": successful_old_day},
                **{day: {"date": day} for day in full_days},
            },
            failed.id: {failed_old_day: {"date": failed_old_day}},
        }
    )

    results = service._sync_daily_batch_groups(
        symbols,
        {symbol.code: full_days for symbol in symbols},
        full_days=full_days,
    )

    assert results[successful.code].status == "success"
    assert results[failed.code].status == "failed"
    assert service.stock_repository.replaced_symbol_ids == [successful.id]
    assert service.stock_repository.upserted_symbol_ids == []
    assert set(service.stock_repository.histories[successful.id]) == set(full_days)
    assert service.stock_repository.histories[failed.id] == {failed_old_day: {"date": failed_old_day}}


def test_replace_daily_history_uses_one_transaction_for_delete_and_insert():
    statements = []
    transactions = []

    class _Session:
        def execute(self, statement, *_args):
            statements.append(statement)
            return SimpleNamespace(rowcount=3)

    class _Database:
        @contextmanager
        def session_scope(self):
            transactions.append("begin")
            yield _Session()
            transactions.append("commit")

    repository = StockRepository(_Database())
    rows = [
        {
            "date": date(2025, 1, 2),
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 100.0,
        }
    ]

    stats = repository.replace_daily_history(1, rows, "tickflow")

    assert transactions == ["begin", "commit"]
    assert len(statements) == 2
    assert str(statements[0]).startswith("DELETE FROM stock_daily")
    assert str(statements[1]).startswith("INSERT INTO stock_daily")
    assert stats.inserted_rows == 1
    assert stats.deleted_rows == 3


@pytest.mark.parametrize(
    ("sync_mode", "expected_windows"),
    [("incremental", [5 * 365, 60]), ("full", [5 * 365, 5 * 365])],
)
def test_sync_mode_preserves_sixty_day_incremental_and_five_year_full_windows(sync_mode, expected_windows):
    symbol = SimpleNamespace(id=1, code="600000.SH")
    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = "CN"
    service.sync_mode = sync_mode
    service.config = SimpleNamespace(
        market_data_initial_daily_days=5 * 365,
        market_data_refresh_daily_days=60,
        market_data_retention_daily_days=10 * 365,
    )
    service.load_scope = lambda: [symbol]
    requested_windows = []

    def refresh_days(natural_days):
        requested_windows.append(natural_days)
        return [date(2025, 1, 2), date(2025, 1, 3)]

    service._refresh_days = refresh_days
    service.stock_repository = SimpleNamespace(
        has_daily_data=lambda _symbol_id: True,
    )
    service._sync_daily_batch_groups = lambda _symbols, _days, **_kwargs: {
        symbol.code: DailyResult("success", providers=["tickflow"])
    }

    summary = service.run()

    assert requested_windows == expected_windows
    assert summary["sync_mode"] == sync_mode


@pytest.mark.parametrize(("market", "key"), [("CN", "cn_daily_sync"), ("US", "us_daily_sync")])
def test_scheduled_daily_scope_reads_only_the_explicit_daily_sync_universe(market, key):
    calls = []
    expected = SimpleNamespace(
        code="600000.SH" if market == "CN" else "AAPL.US",
        market=market,
        listing_status="ACTIVE",
    )
    service = MarketDataSyncService.__new__(MarketDataSyncService)
    service.market = market
    service.universe_resolver = SimpleNamespace(
        resolve_universe=lambda requested: calls.append(requested) or (expected,)
    )

    assert service.load_scope() == [expected]
    assert calls == [key]


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
    summary = service._summarize(
        [SymbolResult(symbol.code, results[symbol.code]) for symbol in symbols],
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


@pytest.mark.parametrize(
    "local_days",
    [
        [date(2025, 1, 2), date(2025, 2, 6)],
        [date(2025, 1, 2), date(2025, 2, 5)],
        [],
        [date(2019, 1, 2)],
    ],
)
def test_db_fresh_batches_tail_merges_remote_over_db_without_writes(local_days):
    codes = ["600000.SH", "000001.SZ"]
    end = date(2025, 2, 6)
    remote_days = [date(2025, 2, 5), end]
    provider = _DailyProvider(
        "daily",
        {code: [replace(_bar_on(code, "daily", day), close=42, high=43) for day in remote_days] for code in codes},
    )
    registry = ProviderRegistry()
    registry.register("daily", provider, capabilities={DAILY_BARS})
    stocks = _PolicyStockRepository([_stored_policy_row(day) for day in local_days])
    service = MarketDataService(
        registry,
        instrument_repository=SimpleNamespace(
            get_by_codes=lambda codes: {code: SimpleNamespace(id=7, code=code, market="CN") for code in codes}
        ),
        stock_repository=stocks,
    )
    result = service.get_daily_bars(
        codes, date(2020, 1, 1), end, adjustment="forward", providers=["daily"], source_policy="db_fresh"
    )
    fresh = bool(local_days and max(local_days) == end)
    assert len(provider.requests) == (0 if fresh else 1)
    if not fresh:
        request = provider.requests[0]
        assert request.symbols == tuple(codes)
        assert request.start_date == (
            max(date(2020, 1, 1), max(local_days) - timedelta(days=10)) if local_days else date(2020, 1, 1)
        )
        assert result.data[codes[0]][-1].close == 42
        assert result.data[codes[0]][-2].close == 42
    if local_days and local_days[0] == date(2025, 1, 2):
        assert result.data[codes[0]][0].trade_date == local_days[0]
    assert len({bar.trade_date for bar in result.data[codes[0]]}) == len(result.data[codes[0]])
    assert stocks.upserts == []


def test_db_fresh_two_thousand_symbols_use_three_db_queries_and_two_remote_batches():
    from sqlalchemy import create_engine, event, func, select
    from sqlalchemy.orm import Session
    from finance_analysis.database.models.stock import Instrument, StockDaily
    from finance_analysis.database.repositories.stock import InstrumentRepository

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Instrument.__table__.create(engine)
    StockDaily.__table__.create(engine)
    codes = [f"{600000 + index}.SH" for index in range(2000)]
    end = date(2026, 9, 4)
    fresh = set(codes[:700])
    stale = set(codes[700:1400])
    missing = set(codes[1400:])
    with Session(engine) as session:
        session.add_all(
            Instrument(id=index + 1, code=code, market="CN", name=code) for index, code in enumerate(codes[:-1])
        )  # also cover an unknown Instrument
        session.flush()
        session.add_all(
            StockDaily(
                id=index + 1,
                instrument_id=index + 1,
                date=end if code in fresh else end - timedelta(days=1),
                open=10,
                high=11,
                low=9,
                close=10.5,
                volume=100,
                data_source="TEST",
            )
            for index, code in enumerate(codes[:1400])
        )
        session.commit()

    class Database:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

    provider = _DailyProvider("daily", {code: [_bar_on(code, "daily", end)] for code in codes})
    registry = ProviderRegistry()
    registry.register("daily", provider, capabilities={DAILY_BARS})
    database = Database()
    service = MarketDataService(
        registry, instrument_repository=InstrumentRepository(database), stock_repository=StockRepository(database)
    )
    statements = []

    def record_query(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_query)
    result = service.get_daily_bars(
        codes, end - timedelta(days=500), end, adjustment="forward", providers=["daily"], source_policy="db_fresh"
    )
    event.remove(engine, "before_cursor_execute", record_query)
    assert len(statements) == 3
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert len(provider.requests) == 2
    assert set(provider.requests[0].symbols) == missing
    assert provider.requests[0].start_date == end - timedelta(days=500)
    assert set(provider.requests[1].symbols) == stale
    assert provider.requests[1].start_date == end - timedelta(days=11)
    assert set(result.data) == set(codes)
    assert all(bars[-1].trade_date == end for bars in result.data.values())
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(StockDaily)) == 1400
        assert session.scalar(select(func.count()).select_from(Instrument)) == 1999
    engine.dispose()

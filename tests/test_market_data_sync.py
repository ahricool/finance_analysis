from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import text

from finance_analysis.database import DatabaseManager
from finance_analysis.database.models.stock import (
    StockAdjustmentFactor,
    StockCorporateAction,
    StockDaily,
    validate_market_data_code,
)
from finance_analysis.database.repositories.adjustment import (
    AdjustmentWriteStats,
    StockAdjustmentRepository,
    stable_row_hash,
)
from finance_analysis.database.repositories.stock import (
    MarketDataSymbolRepository,
    StockRepository,
    UpsertStats,
)
from finance_analysis.database.seed import seed_market_data_reference_symbols
from finance_analysis.integrations.market_data.config import DataProviderConfig
from finance_analysis.integrations.market_data.history import AdjustmentData, HistoricalProviderError
from finance_analysis.integrations.market_data.providers.akshare import AkshareFetcher
from finance_analysis.integrations.market_data.providers.efinance import EfinanceFetcher
from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.integrations.market_data.providers.yfinance import YfinanceFetcher
from finance_analysis.stocks.reference_data.stock_index import CSI300_STOCK_INDEX, SP500_STOCK_INDEX
from finance_analysis.tasks.celery.jobs.market_data_sync.models import ProviderBars, RoutedAdjustment, RoutedBars
from finance_analysis.tasks.celery.jobs.market_data_sync.provider_router import (
    MARKET_PROVIDER_PRIORITY,
    MarketDataProviderRouter,
    default_providers,
)
from finance_analysis.tasks.celery.jobs.market_data_sync.service import (
    MarketDataSyncError,
    MarketDataSyncService,
)
from finance_analysis.tasks.celery.jobs.market_data_sync.validator import enrich_daily_vwap, validate_daily_bars


def _symbol(code: str = "AAPL.US", symbol_id: int = 1, market: str = "US"):
    return SimpleNamespace(id=symbol_id, market=market, code=code, sync_daily=True, sync_minute=False)


def _daily(day: date, close: float = 10.0, amount: float | None = 1000.0):
    return {
        "date": day,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 100,
        "amount": amount,
    }


def _service(market: str = "US", **overrides):
    watchlist = MagicMock()
    watchlist.list_all.return_value = []
    defaults = {
        "symbol_repository": MagicMock(),
        "stock_repository": MagicMock(),
        "adjustment_repository": MagicMock(),
        "watchlist_repository": watchlist,
        "router": MagicMock(),
        "config": DataProviderConfig(),
        "now": datetime(2026, 7, 20, 23, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return MarketDataSyncService(market, **defaults)


def test_reference_constituents_have_expected_cardinality_and_canonical_cn_codes():
    assert len(SP500_STOCK_INDEX) == 503
    assert len(CSI300_STOCK_INDEX) == 300
    assert all(code.endswith((".SH", ".SZ")) for code in CSI300_STOCK_INDEX)
    assert "AAPL" in SP500_STOCK_INDEX
    assert "600519.SH" in CSI300_STOCK_INDEX


def test_reference_seed_is_idempotent_daily_only_for_both_markets():
    repository = MagicMock()
    repository.upsert_symbols.side_effect = [503, 300, 14, 3]
    with patch(
        "finance_analysis.database.repositories.stock.MarketDataSymbolRepository",
        return_value=repository,
    ):
        result = seed_market_data_reference_symbols(MagicMock())
    assert result == {"US": 503, "CN": 300}
    us_rows = list(repository.upsert_symbols.call_args_list[0].args[0])
    cn_rows = list(repository.upsert_symbols.call_args_list[1].args[0])
    assert len(us_rows) == 503 and len(cn_rows) == 300
    assert all(row["sync_daily"] and not row["sync_minute"] for row in [*us_rows, *cn_rows])
    assert all(call.kwargs == {} for call in repository.upsert_symbols.call_args_list)
    assert {row["code"] for row in repository.upsert_symbols.call_args_list[3].args[0]} == {
        "510300.SH",
        "510500.SH",
        "159915.SZ",
    }


def test_canonical_symbol_validation_and_provider_conversion():
    assert validate_market_data_code("US", "AAPL.US") == "AAPL.US"
    assert validate_market_data_code("HK", "700.HK") == "700.HK"
    assert validate_market_data_code("CN", "600519.SH") == "600519.SH"
    assert YfinanceFetcher.to_yfinance_symbol("700.HK") == "0700.HK"
    assert YfinanceFetcher.to_yfinance_symbol("BRK.B.US") == "BRK-B"
    assert LongbridgeFetcher.to_longbridge_symbol("AAPL.US") == "AAPL.US"


def test_raw_daily_and_adjustment_orm_boundaries():
    raw_columns = set(StockDaily.__table__.columns.keys())
    assert {"open", "high", "low", "close", "volume", "amount", "vwap", "vwap_source", "vwap_quality"}.issubset(
        raw_columns
    )
    assert not {"adj_close", "qfq_factor", "hfq_factor"} & raw_columns
    assert {"action_date", "action_type", "source_hash"}.issubset(StockCorporateAction.__table__.columns.keys())
    assert {"trade_date", "qfq_factor", "hfq_factor", "adj_close"}.issubset(
        StockAdjustmentFactor.__table__.columns.keys()
    )


def test_daily_validation_discards_bad_rows_and_keeps_valid_provider_rows():
    day = date(2026, 7, 17)
    row = _daily(day, amount=None)
    assert validate_daily_bars(pd.DataFrame([row]), [day])[0]["amount"] is None
    invalid = {**_daily(date(2026, 7, 16)), "open": float("nan")}
    reasons: list[str] = []
    rows = validate_daily_bars(pd.DataFrame([invalid, row]), [date(2026, 7, 16), day], invalid_reasons=reasons)
    assert [item["date"] for item in rows] == [day]
    assert len(reasons) == 1
    assert "open is not finite" in reasons[0]


def test_yfinance_batch_downloads_multiple_us_symbols_once_and_keeps_raw_prices():
    index = pd.DatetimeIndex(["2026-07-17"], name="Date")
    columns = pd.MultiIndex.from_product([["AAPL", "MSFT"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]])
    raw = pd.DataFrame([[1, 2, 0.5, 1.5, 1.4, 10, 3, 4, 2.5, 3.5, 3.4, 20]], index=index, columns=columns)
    symbols = [_symbol("AAPL.US", 1), _symbol("MSFT.US", 2)]
    with patch("yfinance.download", return_value=raw) as download:
        result = YfinanceFetcher().fetch_daily_bars_batch(symbols, date(2026, 7, 17), date(2026, 7, 17))
    assert download.call_count == 1
    assert download.call_args.kwargs["auto_adjust"] is False
    assert download.call_args.kwargs["threads"] is True
    assert result["AAPL.US"].iloc[0]["close"] == 1.5
    assert result["AAPL.US"].iloc[0]["amount"] is None


def test_yfinance_actions_and_adj_close_are_normalized_separately():
    frame = pd.DataFrame(
        {
            "Close": [100.0],
            "Adj Close": [98.0],
            "Dividends": [1.0],
            "Stock Splits": [2.0],
        },
        index=pd.DatetimeIndex(["2026-07-17"], name="Date"),
    )
    data = YfinanceFetcher._normalize_adjustments(frame, {date(2026, 7, 17)})
    assert data.adjustment_factors[0]["qfq_factor"] == pytest.approx(0.98)
    assert {row["action_type"] for row in data.corporate_actions} == {"dividend", "split"}


def test_akshare_raw_history_uses_empty_adjust_and_factor_api_is_separate():
    raw = pd.DataFrame(
        [
            {
                "日期": "2026-07-17",
                "开盘": 10,
                "最高": 11,
                "最低": 9,
                "收盘": 10,
                "成交量": 100,
                "成交额": 100_000,
            }
        ]
    )
    qfq = pd.DataFrame([{"date": "2026-01-01", "qfq_factor": 2.0}])
    hfq = pd.DataFrame([{"date": "2026-01-01", "hfq_factor": 3.0}])
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    with patch("akshare.stock_zh_a_hist", return_value=raw) as history:
        frame = fetcher.fetch_daily_bars(_symbol("600519.SH", market="CN"), date(2026, 7, 17), date(2026, 7, 17))
    assert history.call_args.kwargs["adjust"] == ""
    assert frame.iloc[0]["amount"] == 100_000
    assert frame.iloc[0]["volume"] == 10_000
    normalized = enrich_daily_vwap(validate_daily_bars(frame, [date(2026, 7, 17)]), "AkshareFetcher")
    assert normalized[0]["vwap"] == pytest.approx(10.0)

    with patch("akshare.stock_zh_a_daily", side_effect=[qfq, hfq]) as factors:
        data = fetcher.fetch_adjustment_data(
            _symbol("600519.SH", market="CN"),
            [date(2026, 7, 16), date(2026, 7, 17)],
        )
    assert [call.kwargs["adjust"] for call in factors.call_args_list] == ["qfq-factor", "hfq-factor"]
    assert len(data.adjustment_factors) == 2
    assert data.adjustment_factors[0]["qfq_factor"] == pytest.approx(0.5)


def test_akshare_cn_corporate_actions_normalize_dividend_bonus_and_rights():
    class FakeAk:
        @staticmethod
        def stock_history_dividend_detail(*, symbol, indicator):
            assert symbol == "600519"
            if indicator == "分红":
                return pd.DataFrame([{"除权除息日": "2026-06-20", "派息": 10, "送股": 2, "转增": 1}])
            return pd.DataFrame([{"除权日": "2026-05-10", "配股方案": 3, "配股价格": 8}])

    actions = AkshareFetcher._fetch_corporate_actions(
        FakeAk,
        "CN",
        "600519",
        date(2025, 7, 18),
        date(2026, 7, 17),
    )
    by_type = {row["action_type"]: row for row in actions}
    assert by_type["dividend"]["cash_dividend"] == 1
    assert by_type["bonus"]["bonus_ratio"] == pytest.approx(0.3)
    assert by_type["rights"]["rights_ratio"] == pytest.approx(0.3)


def test_efinance_raw_history_uses_fqt_zero_and_qfq_is_validation_only():
    raw = pd.DataFrame(
        [
            {
                "日期": "2026-07-17",
                "开盘": 10,
                "最高": 11,
                "最低": 9,
                "收盘": 10,
                "成交量": 100,
                "成交额": 1000,
            }
        ]
    )
    fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
    symbol = _symbol("600519.SH", market="CN")
    with patch(
        "finance_analysis.integrations.market_data.providers.efinance._ef_call_with_timeout",
        return_value=raw,
    ) as call:
        fetcher.fetch_daily_bars(symbol, date(2026, 7, 17), date(2026, 7, 17))
        assert call.call_args.kwargs["fqt"] == 0
        fetcher.fetch_qfq_validation_bars(symbol, date(2026, 7, 17), date(2026, 7, 17))
        assert call.call_args.kwargs["fqt"] == 1


def test_market_provider_order_is_explicit_for_all_markets():
    assert [provider.name for provider in default_providers("CN")] == [
        "EfinanceFetcher",
        "AkshareFetcher",
        "LongbridgeFetcher",
    ]
    assert [provider.name for provider in default_providers("HK")] == [
        "AkshareFetcher",
        "EfinanceFetcher",
        "LongbridgeFetcher",
    ]
    assert [provider.name for provider in default_providers("US")] == ["YfinanceFetcher", "LongbridgeFetcher"]
    assert MARKET_PROVIDER_PRIORITY["US"]["YfinanceFetcher"] > MARKET_PROVIDER_PRIORITY["US"]["LongbridgeFetcher"]


def test_router_keeps_primary_rows_and_fallback_fills_only_missing_days():
    days = [date(2026, 7, 16), date(2026, 7, 17)]

    class Provider:
        def __init__(self, name, rows):
            self.name, self.rows = name, rows

        def fetch_daily_bars(self, *_):
            return pd.DataFrame(self.rows)

    primary = Provider("LongbridgeFetcher", [_daily(days[0], 10, 1000)])
    fallback = Provider("YfinanceFetcher", [_daily(days[0], 99, None), _daily(days[1], 11, None)])
    router = MarketDataProviderRouter(
        "US", [primary, fallback], config=DataProviderConfig(market_data_yfinance_max_retries=0), sleep=lambda _: None
    )
    routed = router.fetch_daily(_symbol(), days)
    assert routed.complete
    assert routed.batches[0].rows[0]["close"] == 10
    assert routed.batches[0].rows[0]["vwap"] == 10
    assert routed.batches[0].rows[0]["vwap_quality"] == "calculated"
    assert [row["date"] for row in routed.batches[1].rows] == [days[1]]
    assert routed.batches[1].rows[0]["amount"] is None
    assert routed.batches[1].rows[0]["vwap_quality"] == "estimated"


def test_router_retries_only_retryable_provider_errors():
    day = date(2026, 7, 17)

    class Provider:
        name = "YfinanceFetcher"

        def __init__(self, retryable):
            self.calls, self.retryable = 0, retryable

        def fetch_daily_bars(self, symbol, *_):
            self.calls += 1
            raise HistoricalProviderError(self.name, "US", symbol.code, "daily", "x", "failure", self.retryable)

    fallback = SimpleNamespace(
        name="LongbridgeFetcher",
        fetch_daily_bars=lambda *_: pd.DataFrame([_daily(day)]),
    )
    retryable = Provider(True)
    router = MarketDataProviderRouter(
        "US", [retryable, fallback], config=DataProviderConfig(market_data_yfinance_max_retries=2), sleep=lambda _: None
    )
    router.fetch_daily(_symbol(), [day])
    assert retryable.calls == 3
    non_retryable = Provider(False)
    router = MarketDataProviderRouter(
        "US",
        [non_retryable, fallback],
        config=DataProviderConfig(market_data_yfinance_max_retries=2),
        sleep=lambda _: None,
    )
    router.fetch_daily(_symbol(), [day])
    assert non_retryable.calls == 1


def test_yfinance_primary_uses_prepared_batch_instead_of_per_symbol_request():
    day = date(2026, 7, 17)

    class Longbridge:
        name = "LongbridgeFetcher"

        @staticmethod
        def fetch_daily_bars(*_):
            return pd.DataFrame()

    class Yahoo:
        name = "YfinanceFetcher"

        def __init__(self):
            self.batch_calls = 0
            self.single_calls = 0

        def fetch_daily_bars_batch(self, symbols, *_):
            self.batch_calls += 1
            return {symbols[0].code: pd.DataFrame([_daily(day, amount=None)])}

        def fetch_daily_bars(self, *_):
            self.single_calls += 1
            raise AssertionError("per-symbol Yahoo request must not be used after batch preparation")

    yahoo = Yahoo()
    symbol = _symbol()
    router = MarketDataProviderRouter(
        "US",
        [yahoo, Longbridge()],
        config=DataProviderConfig(market_data_yfinance_max_retries=0),
        sleep=lambda _: None,
    )
    router.prepare_batches([symbol], {symbol.code: [day]}, [])
    routed = router.fetch_daily(symbol, [day])
    assert routed.complete
    assert yahoo.batch_calls == 1
    assert yahoo.single_calls == 0
    assert routed.batches[-1].rows[0]["vwap_quality"] == "estimated"


def test_router_keeps_valid_rows_when_yfinance_batch_contains_pre_listing_nan_rows():
    days = [date(2026, 7, 16), date(2026, 7, 17)]
    frame = pd.DataFrame(
        [
            {**_daily(days[0], amount=None), "open": float("nan")},
            _daily(days[1], amount=None),
        ]
    )
    yahoo = SimpleNamespace(name="YfinanceFetcher", fetch_daily_bars=lambda *_: frame)
    longbridge = SimpleNamespace(name="LongbridgeFetcher", fetch_daily_bars=lambda *_: pd.DataFrame())
    router = MarketDataProviderRouter(
        "US",
        [yahoo, longbridge],
        config=DataProviderConfig(market_data_yfinance_max_retries=0),
        sleep=lambda _: None,
    )

    routed = router.fetch_daily(_symbol("NEW.US"), days)

    assert [row["date"] for row in routed.batches[0].rows] == [days[1]]
    assert routed.missing == [days[0]]
    assert "discarded invalid daily rows=1" in routed.fallback_reasons[0]


def test_scope_is_reference_constituents_plus_market_watchlist_and_deduplicated():
    symbols = MagicMock()
    symbols.list_enabled_daily_by_codes.return_value = [_symbol()]
    watchlist = MagicMock()
    watchlist.list_all.return_value = [
        SimpleNamespace(code="AAPL", name="Apple", market_type="US"),
        SimpleNamespace(code="700", name="Tencent", market_type="HK"),
    ]
    service = _service(symbol_repository=symbols, watchlist_repository=watchlist)
    assert service.load_scope() == [_symbol()]
    selected_codes = symbols.list_enabled_daily_by_codes.call_args.args[1]
    assert "AAPL.US" in selected_codes
    assert "700.HK" not in selected_codes
    assert len(selected_codes) > len(SP500_STOCK_INDEX)
    symbols.upsert_symbols.assert_called_once()
    assert symbols.upsert_symbols.call_args.kwargs == {"overwrite_runtime_flags": False}


def test_refresh_window_uses_configured_natural_days():
    service = _service(config=DataProviderConfig(market_data_refresh_daily_days=60))
    days = service._refresh_days(service.config.market_data_refresh_daily_days)
    assert days[-1] - timedelta(days=59) <= days[0]
    assert days[0] >= days[-1] - timedelta(days=59)
    assert "delete_daily_before" in StockRepository.__dict__


def test_service_result_contains_required_fields_and_marks_missing_amount():
    symbol = _symbol()
    symbols = MagicMock()
    symbols.list_enabled_daily_by_codes.return_value = [symbol]
    stock = MagicMock()
    stock.upsert_daily.return_value = UpsertStats(inserted_rows=1)
    adjustment = MagicMock()
    adjustment.upsert_adjustment_factors.return_value = AdjustmentWriteStats(changed=True, inserted_rows=1)
    adjustment.replace_corporate_actions.return_value = AdjustmentWriteStats()
    router = MagicMock()
    router.fetch_daily.return_value = RoutedBars(
        [
            ProviderBars(
                "YfinanceFetcher",
                300,
                [
                    {
                        **_daily(date(2026, 7, 17), amount=None),
                        "vwap": 10.0,
                        "vwap_source": "hlc3",
                        "vwap_quality": "estimated",
                    }
                ],
            )
        ],
        [],
        ["YfinanceFetcher"],
        "range",
    )
    router.fetch_adjustment.return_value = RoutedAdjustment(
        "YfinanceFetcher",
        AdjustmentData([], [{"trade_date": date(2026, 7, 17), "qfq_factor": 1.0}]),
    )
    service = _service(
        symbol_repository=symbols,
        stock_repository=stock,
        adjustment_repository=adjustment,
        router=router,
    )
    result = service.run()
    required = {
        "market",
        "symbol_count",
        "success_symbols",
        "partial_symbols",
        "failed_symbols",
        "inserted_rows",
        "updated_rows",
        "provider_counts",
        "missing_amount_symbols",
        "fallback_reasons",
        "provider_vwap_symbols",
        "calculated_vwap_symbols",
        "estimated_vwap_symbols",
        "missing_vwap_symbols",
        "unsupported_symbol_count",
        "unsupported_symbols",
    }
    assert required.issubset(result)
    assert result["market"] == "US"
    assert result["missing_amount_symbols"] == ["AAPL.US"]
    assert result["estimated_vwap_symbols"] == ["AAPL.US"]
    assert result["adjustment_changed_symbols"] == ["AAPL.US"]


def test_all_symbols_failed_raises_task_level_error():
    symbols = MagicMock()
    symbols.list_enabled_daily_by_codes.return_value = [_symbol()]
    router = MagicMock()
    router.fetch_daily.return_value = RoutedBars([], [date(2026, 7, 17)], [], "range")
    router.fetch_adjustment.return_value = RoutedAdjustment(None, None)
    service = _service(symbol_repository=symbols, router=router)
    with pytest.raises(MarketDataSyncError, match="All 1 US symbols failed"):
        service.run()


def test_longbridge_turnover_calculates_vwap_from_same_provider_row():
    day = date(2026, 7, 17)
    rows = enrich_daily_vwap(
        validate_daily_bars(pd.DataFrame([_daily(day, close=10.5, amount=1050.0)]), [day]),
        "LongbridgeFetcher",
    )
    assert rows[0]["vwap"] == pytest.approx(10.5)
    assert rows[0]["vwap_source"] == "amount_div_volume"
    assert rows[0]["vwap_quality"] == "calculated"


def test_provider_vwap_takes_priority_over_amount_calculation():
    day = date(2026, 7, 17)
    row = {**_daily(day, close=10.0, amount=1000.0), "vwap": 10.2}
    rows = enrich_daily_vwap(validate_daily_bars(pd.DataFrame([row]), [day]), "LongbridgeFetcher")
    assert rows[0]["vwap"] == pytest.approx(10.2)
    assert rows[0]["vwap_source"] == "longbridge"
    assert rows[0]["vwap_quality"] == "provider"


def test_yfinance_uses_hlc3_without_fabricating_amount():
    day = date(2026, 7, 17)
    row = _daily(day, close=10.0, amount=None)
    rows = enrich_daily_vwap(validate_daily_bars(pd.DataFrame([row]), [day]), "YfinanceFetcher")
    assert rows[0]["vwap"] == pytest.approx(10.0)
    assert rows[0]["vwap_source"] == "hlc3"
    assert rows[0]["vwap_quality"] == "estimated"
    assert rows[0]["amount"] is None


def test_new_symbols_use_400_days_and_existing_symbols_use_60_days():
    new_symbol = _symbol("AAPL.US", 1)
    existing_symbol = _symbol("MSFT.US", 2)
    symbols = MagicMock()
    symbols.list_enabled_daily_by_codes.return_value = [new_symbol, existing_symbol]
    stock = MagicMock()
    stock.has_daily_data.side_effect = [False, True]
    stock.upsert_daily.return_value = UpsertStats(inserted_rows=1)
    stock.delete_daily_before.return_value = 0
    adjustment = MagicMock()
    adjustment.has_corporate_action_changes.return_value = False
    adjustment.replace_corporate_actions.return_value = AdjustmentWriteStats()
    adjustment.upsert_adjustment_factors.return_value = AdjustmentWriteStats()
    adjustment.delete_before.return_value = 0
    router = MagicMock()
    router.fetch_daily.side_effect = lambda symbol, days: RoutedBars(
        [
            ProviderBars(
                "LongbridgeFetcher",
                300,
                [
                    {
                        **_daily(days[-1]),
                        "vwap": 10.0,
                        "vwap_source": "amount_div_volume",
                        "vwap_quality": "calculated",
                    }
                ],
            )
        ],
        [],
        ["LongbridgeFetcher"],
        "range",
    )
    router.fetch_adjustment.side_effect = lambda symbol, days: RoutedAdjustment(
        "YfinanceFetcher",
        AdjustmentData([], [{"trade_date": item, "qfq_factor": 1.0} for item in days]),
    )
    service = _service(
        symbol_repository=symbols,
        stock_repository=stock,
        adjustment_repository=adjustment,
        router=router,
        config=DataProviderConfig(
            market_data_initial_daily_days=400,
            market_data_refresh_daily_days=60,
            market_data_retention_daily_days=400,
        ),
    )
    service.run()
    windows = router.prepare_batches.call_args.args[1]
    assert windows["AAPL.US"][0] >= windows["AAPL.US"][-1] - timedelta(days=399)
    assert windows["AAPL.US"][0] <= windows["AAPL.US"][-1] - timedelta(days=390)
    assert windows["MSFT.US"][0] >= windows["MSFT.US"][-1] - timedelta(days=59)
    assert len(windows["AAPL.US"]) > len(windows["MSFT.US"])


@pytest.mark.parametrize("market", ["US", "CN"])
def test_full_sync_uses_initial_window_for_existing_symbols_in_both_markets(market):
    symbol = _symbol("AAPL.US" if market == "US" else "600519.SH", market=market)
    symbols = MagicMock()
    symbols.list_enabled_daily_by_codes.return_value = [symbol]
    stock = MagicMock()
    stock.has_daily_data.return_value = True
    stock.upsert_daily.return_value = UpsertStats(inserted_rows=1)
    stock.delete_daily_before.return_value = 0
    adjustment = MagicMock()
    adjustment.has_corporate_action_changes.return_value = False
    adjustment.replace_corporate_actions.return_value = AdjustmentWriteStats()
    adjustment.upsert_adjustment_factors.return_value = AdjustmentWriteStats()
    adjustment.delete_before.return_value = 0
    router = MagicMock()
    router.fetch_daily.side_effect = lambda _, days: RoutedBars(
        [
            ProviderBars(
                "YfinanceFetcher",
                400,
                [
                    {
                        **_daily(days[-1]),
                        "vwap": 10.0,
                        "vwap_source": "hlc3",
                        "vwap_quality": "estimated",
                    }
                ],
            )
        ],
        [],
        ["YfinanceFetcher"],
        "range",
    )
    router.fetch_adjustment.side_effect = lambda _, days: RoutedAdjustment(
        "YfinanceFetcher",
        AdjustmentData([], [{"trade_date": item, "qfq_factor": 1.0} for item in days]),
    )
    service = _service(
        market=market,
        sync_mode="full",
        symbol_repository=symbols,
        stock_repository=stock,
        adjustment_repository=adjustment,
        router=router,
        config=DataProviderConfig(
            market_data_initial_daily_days=400,
            market_data_refresh_daily_days=60,
            market_data_retention_daily_days=400,
        ),
    )

    result = service.run()

    window = router.prepare_batches.call_args.args[1][symbol.code]
    assert window[0] <= window[-1] - timedelta(days=390)
    assert result["sync_mode"] == "full"
    stock.has_daily_data.assert_not_called()


def test_retention_cleanup_runs_after_successful_upsert():
    day = date(2026, 7, 17)
    cutoff = date(2025, 6, 14)
    events: list[str] = []
    stock = MagicMock()
    stock.upsert_daily.side_effect = lambda *_: events.append("upsert") or UpsertStats(inserted_rows=1)
    stock.delete_daily_before.side_effect = lambda *_: events.append("delete") or 3
    adjustment = MagicMock()
    adjustment.replace_corporate_actions.return_value = AdjustmentWriteStats()
    adjustment.upsert_adjustment_factors.return_value = AdjustmentWriteStats()
    adjustment.delete_before.return_value = 0
    router = MagicMock()
    router.fetch_daily.return_value = RoutedBars(
        [
            ProviderBars(
                "LongbridgeFetcher",
                300,
                [
                    {
                        **_daily(day),
                        "vwap": 10.0,
                        "vwap_source": "amount_div_volume",
                        "vwap_quality": "calculated",
                    }
                ],
            )
        ],
        [],
        ["LongbridgeFetcher"],
        "range",
    )
    router.fetch_adjustment.return_value = RoutedAdjustment(
        "YfinanceFetcher", AdjustmentData([], [{"trade_date": day, "qfq_factor": 1.0}])
    )
    result = _service(stock_repository=stock, adjustment_repository=adjustment, router=router)._sync_symbol(
        _symbol(), [day], [day], cutoff
    )
    assert events == ["upsert", "delete"]
    assert result.daily.deleted_rows == 3
    stock.delete_daily_before.assert_called_once_with(1, cutoff)


def test_failed_sync_does_not_delete_existing_daily_history():
    day = date(2026, 7, 17)
    stock = MagicMock()
    adjustment = MagicMock()
    adjustment.replace_corporate_actions.return_value = AdjustmentWriteStats()
    adjustment.upsert_adjustment_factors.return_value = AdjustmentWriteStats()
    adjustment.delete_before.return_value = 0
    router = MagicMock()
    router.fetch_daily.return_value = RoutedBars([], [day], [], "range")
    router.fetch_adjustment.return_value = RoutedAdjustment(
        "YfinanceFetcher", AdjustmentData([], [{"trade_date": day, "qfq_factor": 1.0}])
    )
    result = _service(stock_repository=stock, adjustment_repository=adjustment, router=router)._sync_symbol(
        _symbol(), [day], [day], date(2025, 6, 14)
    )
    assert result.daily.status == "failed"
    stock.delete_daily_before.assert_not_called()
    adjustment.delete_before.assert_not_called()


def test_hk_watchlist_is_reported_as_unsupported_without_failure():
    symbols = MagicMock()
    symbols.list_enabled_daily_by_codes.return_value = []
    watchlist = MagicMock()
    watchlist.list_all.return_value = [SimpleNamespace(code="700", name="Tencent", market_type="HK")]
    result = _service(
        market="CN",
        symbol_repository=symbols,
        watchlist_repository=watchlist,
    ).run()
    assert result["unsupported_symbol_count"] == 1
    assert result["unsupported_symbols"] == [
        {
            "code": "700.HK",
            "market": "HK",
            "reason": "HK daily synchronization is temporarily unsupported",
        }
    ]
    assert result["failed_symbols"] == 0
    assert result["partial_symbols"] == 0


def test_new_corporate_action_replaces_complete_retention_factor_window():
    days = [date(2026, 7, 16), date(2026, 7, 17)]
    adjustment = MagicMock()
    adjustment.has_corporate_action_changes.return_value = True
    adjustment.replace_corporate_actions.return_value = AdjustmentWriteStats(changed=True)
    adjustment.replace_adjustment_factors.return_value = AdjustmentWriteStats(changed=True, updated_rows=2)
    router = MagicMock()
    router.fetch_adjustment.return_value = RoutedAdjustment(
        "YfinanceFetcher",
        AdjustmentData(
            [{"action_date": days[-1], "action_type": "dividend", "cash_dividend": 1.0}],
            [{"trade_date": item, "qfq_factor": 0.9} for item in days],
        ),
    )
    result = _service(adjustment_repository=adjustment, router=router)._sync_adjustment(_symbol(), days)
    assert result.changed
    adjustment.replace_adjustment_factors.assert_called_once()
    adjustment.upsert_adjustment_factors.assert_not_called()


def test_partial_factor_response_only_upserts_and_never_replaces_window():
    days = [date(2026, 7, 16), date(2026, 7, 17)]
    adjustment = MagicMock()
    adjustment.has_corporate_action_changes.return_value = True
    adjustment.replace_corporate_actions.return_value = AdjustmentWriteStats(changed=True)
    adjustment.upsert_adjustment_factors.return_value = AdjustmentWriteStats(changed=True, updated_rows=1)
    router = MagicMock()
    router.fetch_adjustment.return_value = RoutedAdjustment(
        "YfinanceFetcher",
        AdjustmentData(
            [{"action_date": days[-1], "action_type": "split", "split_ratio": 2.0}],
            [{"trade_date": days[-1], "qfq_factor": 0.5}],
            adjustment_factors_complete=False,
        ),
    )
    result = _service(adjustment_repository=adjustment, router=router)._sync_adjustment(_symbol(), days)
    assert result.changed
    adjustment.upsert_adjustment_factors.assert_called_once()
    adjustment.replace_adjustment_factors.assert_not_called()


def test_stable_adjustment_hash_ignores_mapping_order():
    assert stable_row_hash({"a": 1, "b": 2}) == stable_row_hash({"b": 2, "a": 1})


@pytest.mark.skipif(not __import__("os").getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_adjustment_repository_replaces_only_changed_symbol_window():
    db = DatabaseManager.get_instance()
    symbol = MarketDataSymbolRepository(db).get_by_code("AAPL.US")
    repository = StockAdjustmentRepository(db)
    day = date(2040, 1, 3)
    factor = {"trade_date": day, "qfq_factor": 0.9, "hfq_factor": None, "adj_close": 90.0}
    action = {
        "action_date": day,
        "action_type": "dividend",
        "cash_dividend": 1.0,
        "raw_payload": {"dividend": 1.0},
    }
    with db._engine.begin() as connection:
        connection.execute(
            text("DELETE FROM stock_adjustment_factor WHERE symbol_id=:id AND trade_date=:day"),
            {"id": symbol.id, "day": day},
        )
        connection.execute(
            text("DELETE FROM stock_corporate_action WHERE symbol_id=:id AND action_date=:day"),
            {"id": symbol.id, "day": day},
        )
    try:
        first = repository.replace_adjustment_factors(symbol.id, day, day, [factor], "YfinanceFetcher")
        assert first.changed and first.inserted_rows == 1
        assert not repository.replace_adjustment_factors(symbol.id, day, day, [factor], "YfinanceFetcher").changed
        changed = repository.replace_adjustment_factors(
            symbol.id,
            day,
            day,
            [{**factor, "qfq_factor": 0.8}],
            "YfinanceFetcher",
        )
        assert changed.changed and changed.updated_rows == 1
        assert repository.replace_corporate_actions(symbol.id, day, day, [action], "YfinanceFetcher").inserted_rows == 1
    finally:
        with db._engine.begin() as connection:
            connection.execute(
                text("DELETE FROM stock_adjustment_factor WHERE symbol_id=:id AND trade_date=:day"),
                {"id": symbol.id, "day": day},
            )
            connection.execute(
                text("DELETE FROM stock_corporate_action WHERE symbol_id=:id AND action_date=:day"),
                {"id": symbol.id, "day": day},
            )


@pytest.mark.skipif(not __import__("os").getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_symbol_seed_upsert_preserves_runtime_flags_by_default():
    db = DatabaseManager.get_instance()
    repository = MarketDataSymbolRepository(db)
    code = "VWAPSAFE.US"
    with db._engine.begin() as connection:
        connection.execute(text("DELETE FROM market_data_symbol WHERE code=:code"), {"code": code})
    try:
        repository.upsert_symbols(
            [
                {
                    "market": "US",
                    "code": code,
                    "name": "Original",
                    "enabled": False,
                    "sync_daily": False,
                    "sync_minute": True,
                }
            ]
        )
        repository.upsert_symbols(
            [
                {
                    "market": "US",
                    "code": code,
                    "name": "Updated",
                    "enabled": True,
                    "sync_daily": True,
                    "sync_minute": False,
                }
            ]
        )
        stored = repository.get_by_code(code)
        assert stored.name == "Updated"
        assert stored.enabled is False
        assert stored.sync_daily is False
        assert stored.sync_minute is True
    finally:
        with db._engine.begin() as connection:
            connection.execute(text("DELETE FROM market_data_symbol WHERE code=:code"), {"code": code})


@pytest.mark.skipif(not __import__("os").getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_partial_adjustment_factor_upsert_preserves_other_dates():
    db = DatabaseManager.get_instance()
    symbol = MarketDataSymbolRepository(db).get_by_code("AAPL.US")
    repository = StockAdjustmentRepository(db)
    days = [date(2040, 2, 1), date(2040, 2, 2)]
    with db._engine.begin() as connection:
        connection.execute(
            text("DELETE FROM stock_adjustment_factor WHERE symbol_id=:id AND trade_date BETWEEN :start AND :end"),
            {"id": symbol.id, "start": days[0], "end": days[-1]},
        )
    try:
        repository.replace_adjustment_factors(
            symbol.id,
            days[0],
            days[-1],
            [{"trade_date": item, "qfq_factor": 1.0} for item in days],
            "YfinanceFetcher",
        )
        repository.upsert_adjustment_factors(
            symbol.id,
            days[0],
            days[-1],
            [{"trade_date": days[-1], "qfq_factor": 0.5}],
            "YfinanceFetcher",
        )
        with db.get_session() as session:
            rows = session.execute(
                text(
                    "SELECT trade_date, qfq_factor FROM stock_adjustment_factor "
                    "WHERE symbol_id=:id AND trade_date BETWEEN :start AND :end ORDER BY trade_date"
                ),
                {"id": symbol.id, "start": days[0], "end": days[-1]},
            ).all()
        assert [(row.trade_date, row.qfq_factor) for row in rows] == [
            (days[0], 1.0),
            (days[-1], 0.5),
        ]
    finally:
        with db._engine.begin() as connection:
            connection.execute(
                text("DELETE FROM stock_adjustment_factor WHERE symbol_id=:id AND trade_date BETWEEN :start AND :end"),
                {"id": symbol.id, "start": days[0], "end": days[-1]},
            )

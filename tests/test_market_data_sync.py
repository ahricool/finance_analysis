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
from finance_analysis.database.seed import seed_market_data_reference_symbols
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
    RAW_REFRESH_NATURAL_DAYS,
    MarketDataSyncError,
    MarketDataSyncService,
)
from finance_analysis.tasks.celery.jobs.market_data_sync.validator import (
    MarketDataValidationError,
    validate_daily_bars,
)


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
    repository.upsert_symbols.side_effect = [503, 300]
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


def test_canonical_symbol_validation_and_provider_conversion():
    assert validate_market_data_code("US", "AAPL.US") == "AAPL.US"
    assert validate_market_data_code("HK", "700.HK") == "700.HK"
    assert validate_market_data_code("CN", "600519.SH") == "600519.SH"
    assert YfinanceFetcher.to_yfinance_symbol("700.HK") == "0700.HK"
    assert YfinanceFetcher.to_yfinance_symbol("BRK.B.US") == "BRK-B"
    assert LongbridgeFetcher.to_longbridge_symbol("AAPL.US") == "AAPL.US"


def test_raw_daily_and_adjustment_orm_boundaries():
    raw_columns = set(StockDaily.__table__.columns.keys())
    assert {"open", "high", "low", "close", "volume", "amount"}.issubset(raw_columns)
    assert not {"adj_close", "qfq_factor", "hfq_factor"} & raw_columns
    assert {"action_date", "action_type", "source_hash"}.issubset(
        StockCorporateAction.__table__.columns.keys()
    )
    assert {"trade_date", "qfq_factor", "hfq_factor", "adj_close"}.issubset(
        StockAdjustmentFactor.__table__.columns.keys()
    )


def test_daily_validation_requires_amount_field_but_allows_missing_provider_value():
    day = date(2026, 7, 17)
    row = _daily(day, amount=None)
    assert validate_daily_bars(pd.DataFrame([row]), [day])[0]["amount"] is None
    row.pop("amount")
    with pytest.raises(MarketDataValidationError, match="amount field is missing"):
        validate_daily_bars(pd.DataFrame([row]), [day])


def test_yfinance_batch_downloads_multiple_us_symbols_once_and_keeps_raw_prices():
    index = pd.DatetimeIndex(["2026-07-17"], name="Date")
    columns = pd.MultiIndex.from_product(
        [["AAPL", "MSFT"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
    )
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
                "成交额": 1000,
            }
        ]
    )
    qfq = pd.DataFrame([{"date": "2026-01-01", "qfq_factor": 2.0}])
    hfq = pd.DataFrame([{"date": "2026-01-01", "hfq_factor": 3.0}])
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    with patch("akshare.stock_zh_a_hist", return_value=raw) as history:
        frame = fetcher.fetch_daily_bars(_symbol("600519.SH", market="CN"), date(2026, 7, 17), date(2026, 7, 17))
    assert history.call_args.kwargs["adjust"] == ""
    assert frame.iloc[0]["amount"] == 1000

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
                return pd.DataFrame(
                    [{"除权除息日": "2026-06-20", "派息": 10, "送股": 2, "转增": 1}]
                )
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
        "EfinanceFetcher", "AkshareFetcher", "LongbridgeFetcher"
    ]
    assert [provider.name for provider in default_providers("HK")] == [
        "AkshareFetcher", "EfinanceFetcher", "LongbridgeFetcher"
    ]
    assert [provider.name for provider in default_providers("US")] == [
        "YfinanceFetcher", "LongbridgeFetcher"
    ]
    assert MARKET_PROVIDER_PRIORITY["US"]["YfinanceFetcher"] > MARKET_PROVIDER_PRIORITY["US"]["LongbridgeFetcher"]


def test_router_keeps_primary_rows_and_fallback_fills_only_missing_days():
    days = [date(2026, 7, 16), date(2026, 7, 17)]

    class Provider:
        def __init__(self, name, rows):
            self.name, self.rows = name, rows

        def fetch_daily_bars(self, *_):
            return pd.DataFrame(self.rows)

    primary = Provider("YfinanceFetcher", [_daily(days[0], 10, None)])
    fallback = Provider("LongbridgeFetcher", [_daily(days[0], 99), _daily(days[1], 11)])
    router = MarketDataProviderRouter(
        "US", [primary, fallback], config=DataProviderConfig(market_data_yfinance_max_retries=0), sleep=lambda _: None
    )
    routed = router.fetch_daily(_symbol(), days)
    assert routed.complete
    assert routed.batches[0].rows[0]["close"] == 10
    assert [row["date"] for row in routed.batches[1].rows] == [days[1]]


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


def test_scope_is_reference_constituents_plus_market_watchlist_and_deduplicated():
    symbols = MagicMock()
    symbols.list_enabled_daily_by_codes.return_value = [_symbol()]
    watchlist = MagicMock()
    watchlist.list_all.return_value = [
        SimpleNamespace(code="AAPL", name="Apple", market_type="US"),
        SimpleNamespace(code="700", name="Tencent", market_type="HK"),
    ]
    service = _service(symbol_repository=symbols, watchlist_repository=watchlist)
    assert service._load_scope() == [_symbol()]
    selected_codes = symbols.list_enabled_daily_by_codes.call_args.args[1]
    assert "AAPL.US" in selected_codes
    assert "700.HK" not in selected_codes
    assert len(selected_codes) == len(SP500_STOCK_INDEX)
    symbols.upsert_symbols.assert_called_once()


def test_raw_refresh_window_is_always_last_sixty_natural_days_and_never_deletes_history():
    service = _service()
    days = service._refresh_days(RAW_REFRESH_NATURAL_DAYS)
    assert days[-1] - timedelta(days=59) <= days[0]
    assert days[0] >= days[-1] - timedelta(days=59)
    assert "delete_daily_before" not in StockRepository.__dict__


def test_service_result_contains_required_fields_and_marks_missing_amount():
    symbol = _symbol()
    symbols = MagicMock()
    symbols.list_enabled_daily_by_codes.return_value = [symbol]
    stock = MagicMock()
    stock.upsert_daily.return_value = UpsertStats(inserted_rows=1)
    adjustment = MagicMock()
    adjustment.replace_adjustment_factors.return_value = AdjustmentWriteStats(changed=True, inserted_rows=1)
    adjustment.replace_corporate_actions.return_value = AdjustmentWriteStats()
    router = MagicMock()
    router.fetch_daily.return_value = RoutedBars(
        [ProviderBars("YfinanceFetcher", 300, [_daily(date(2026, 7, 17), amount=None)])],
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
        "market", "symbol_count", "success_symbols", "partial_symbols", "failed_symbols",
        "inserted_rows", "updated_rows", "provider_counts", "missing_amount_symbols", "fallback_reasons",
    }
    assert required.issubset(result)
    assert result["market"] == "US"
    assert result["missing_amount_symbols"] == ["AAPL.US"]
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
        assert not repository.replace_adjustment_factors(
            symbol.id, day, day, [factor], "YfinanceFetcher"
        ).changed
        changed = repository.replace_adjustment_factors(
            symbol.id,
            day,
            day,
            [{**factor, "qfq_factor": 0.8}],
            "YfinanceFetcher",
        )
        assert changed.changed and changed.updated_rows == 1
        assert repository.replace_corporate_actions(
            symbol.id, day, day, [action], "YfinanceFetcher"
        ).inserted_rows == 1
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

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import inspect, text

from finance_analysis.database import DatabaseManager
from finance_analysis.database.models.stock import (
    MarketDataSymbol,
    StockDaily,
    StockMinute,
    validate_market_data_code,
)
from finance_analysis.database.repositories.stock import (
    MarketDataSymbolRepository,
    StockRepository,
    UpsertStats,
)
from finance_analysis.integrations.market_data.config import DataProviderConfig
from finance_analysis.integrations.market_data.history import HistoricalProviderError
from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.integrations.market_data.providers.yfinance import YfinanceFetcher
from finance_analysis.tasks.celery.jobs.us_market_data_sync.models import ProviderBars, RoutedBars
from finance_analysis.tasks.celery.jobs.us_market_data_sync.provider_router import HistoricalProviderRouter
from finance_analysis.tasks.celery.jobs.us_market_data_sync.service import USMarketDataSyncService
from finance_analysis.tasks.celery.jobs.us_market_data_sync.validator import (
    MarketDataValidationError,
    expected_minute_times,
    validate_daily_bars,
    validate_minute_bars,
)


def _symbol(code="AAPL.US", symbol_id=1):
    return SimpleNamespace(id=symbol_id, market="US", code=code, sync_daily=True, sync_minute=True)


def _daily(day: date, close: float = 10.0):
    return {"date": day, "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": 100, "amount": None}


def test_canonical_symbol_validation_and_provider_conversion():
    assert validate_market_data_code("US", "AAPL.US") == "AAPL.US"
    assert validate_market_data_code("HK", "700.HK") == "700.HK"
    assert validate_market_data_code("CN", "600519.SH") == "600519.SH"
    assert validate_market_data_code("CN", "000001.SZ") == "000001.SZ"
    for market, code in (("US", "AAPL"), ("HK", "0700.HK"), ("CN", "600519"), ("CN", "600519.US")):
        with pytest.raises(ValueError):
            validate_market_data_code(market, code)
    assert YfinanceFetcher.to_yfinance_symbol("AAPL.US") == "AAPL"
    assert YfinanceFetcher.to_yfinance_symbol("700.HK") == "0700.HK"
    assert YfinanceFetcher.to_yfinance_symbol("600519.SH") == "600519.SS"
    assert LongbridgeFetcher.to_longbridge_symbol("AAPL.US") == "AAPL.US"


def test_raw_orm_schema_has_no_derived_daily_columns():
    columns = set(StockDaily.__table__.columns.keys())
    assert not {"pct_chg", "ma5", "ma10", "ma20", "volume_ratio"} & columns
    assert {"symbol_id", "source_priority", "data_source"}.issubset(columns)
    minute_unique = {tuple(constraint.columns.keys()) for constraint in StockMinute.__table__.constraints}
    assert ("symbol_id", "bar_time") in minute_unique


def test_yfinance_history_is_explicitly_unadjusted_and_amount_is_null():
    raw = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10]},
        index=pd.DatetimeIndex(["2026-07-02"], name="Date"),
    )
    with patch("yfinance.download", return_value=raw) as download:
        frame = YfinanceFetcher().fetch_daily_bars(_symbol(), date(2026, 7, 2), date(2026, 7, 2))
    assert download.call_args.kwargs["auto_adjust"] is False
    assert download.call_args.kwargs["prepost"] is False
    assert frame.iloc[0]["amount"] is None


def test_longbridge_uses_history_endpoint_no_adjust_and_pages():
    class Candle:
        def __init__(self, day):
            self.timestamp = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            self.open, self.high, self.low, self.close = 1, 2, 0.5, 1.5
            self.volume, self.turnover = 10, 20

    context = MagicMock()
    context.history_candlesticks_by_offset.side_effect = [
        [Candle(date(2026, 7, 2)), Candle(date(2026, 7, 1))],
        [Candle(date(2026, 6, 30)), Candle(date(2026, 6, 29))],
    ]
    fetcher = LongbridgeFetcher()
    fetcher._HISTORY_PAGE_SIZE = 2
    fetcher._ctx = context
    frame = fetcher.fetch_daily_bars(_symbol(), date(2026, 6, 29), date(2026, 7, 2))
    from longbridge.openapi import AdjustType

    assert len(frame) == 4
    assert context.history_candlesticks_by_offset.call_count == 2
    assert all(call.args[2] == AdjustType.NoAdjust for call in context.history_candlesticks_by_offset.call_args_list)
    context.candlesticks.assert_not_called()


def test_daily_validation_rejects_invalid_ohlc_and_accepts_null_amount():
    day = date(2026, 7, 2)
    valid = validate_daily_bars(pd.DataFrame([_daily(day)]), [day])
    assert valid[0]["amount"] is None
    invalid = _daily(day)
    invalid["high"] = 0.1
    with pytest.raises(MarketDataValidationError):
        validate_daily_bars(pd.DataFrame([invalid]), [day])


def test_minute_validation_filters_extended_hours_and_converts_dst_to_utc():
    day = date(2026, 7, 2)
    ny = ZoneInfo("America/New_York")
    rows = []
    for local_time in (
        datetime(2026, 7, 2, 9, 29, tzinfo=ny),
        datetime(2026, 7, 2, 9, 30, tzinfo=ny),
        datetime(2026, 7, 2, 16, 0, tzinfo=ny),
    ):
        rows.append({"bar_time": local_time, **{k: v for k, v in _daily(day).items() if k != "date"}})
    valid = validate_minute_bars(pd.DataFrame(rows), day, now=datetime(2026, 7, 3, tzinfo=timezone.utc))
    assert len(valid) == 1
    assert valid[0]["bar_time"] == datetime(2026, 7, 2, 13, 30, tzinfo=timezone.utc)


def test_early_close_expected_minutes_come_from_calendar():
    # 2026-11-27 is the NYSE day after Thanksgiving (13:00 close).
    expected = expected_minute_times(date(2026, 11, 27))
    assert len(expected) == 210


def test_router_keeps_longbridge_rows_and_yfinance_fills_only_missing_daily_day():
    days = [date(2026, 7, 1), date(2026, 7, 2)]

    class Provider:
        def __init__(self, name, priority, rows):
            self.name, self.source_priority, self.rows = name, priority, rows

        def fetch_daily_bars(self, *args):
            return pd.DataFrame(self.rows)

    lb = Provider("LongbridgeFetcher", 100, [_daily(days[0], 10)])
    yf = Provider("YfinanceFetcher", 50, [_daily(days[0], 99), _daily(days[1], 11)])
    router = HistoricalProviderRouter(
        lb, yf, longbridge_concurrency=5, longbridge_retries=0,
        yfinance_concurrency=2, yfinance_retries=0, sleep=lambda _: None,
    )
    routed = router.fetch_daily(_symbol(), days)
    assert routed.complete
    assert routed.batches[0].rows[0]["close"] == 10
    assert [row["date"] for row in routed.batches[1].rows] == [days[1]]


def test_router_retries_only_retryable_errors():
    class Provider:
        name = "LongbridgeFetcher"
        source_priority = 100

        def __init__(self, retryable):
            self.calls, self.retryable = 0, retryable

        def fetch_daily_bars(self, symbol, start, end):
            self.calls += 1
            raise HistoricalProviderError(self.name, "US", symbol.code, "daily", "x", "failure", self.retryable)

    fallback = SimpleNamespace(
        name="YfinanceFetcher", source_priority=50,
        fetch_daily_bars=lambda symbol, start, end: pd.DataFrame([_daily(start)]),
    )
    retryable = Provider(True)
    router = HistoricalProviderRouter(
        retryable, fallback, longbridge_concurrency=5, longbridge_retries=2,
        yfinance_concurrency=2, yfinance_retries=0, sleep=lambda _: None,
    )
    router.fetch_daily(_symbol(), [date(2026, 7, 2)])
    assert retryable.calls == 3
    non_retryable = Provider(False)
    router = HistoricalProviderRouter(
        non_retryable, fallback, longbridge_concurrency=5, longbridge_retries=2,
        yfinance_concurrency=2, yfinance_retries=0, sleep=lambda _: None,
    )
    router.fetch_daily(_symbol(), [date(2026, 7, 2)])
    assert non_retryable.calls == 1


def test_daily_and_minute_bootstrap_modes_are_independent():
    stock_repo = MagicMock()
    stock_repo.has_daily_data.return_value = True
    stock_repo.has_minute_data.return_value = False
    config = DataProviderConfig(
        market_data_repair_daily_days=14,
        market_data_initial_minute_days=3,
    )
    service = USMarketDataSyncService(
        symbol_repository=MagicMock(), stock_repository=stock_repo,
        router=MagicMock(), config=config,
        now=datetime(2026, 7, 2, 22, tzinfo=timezone.utc),
    )
    assert service._daily_window(_symbol()).mode == "repair"
    assert len(service._daily_window(_symbol()).trading_days) == 14
    assert service._minute_window(_symbol()).mode == "bootstrap"
    assert len(service._minute_window(_symbol()).trading_days) == 3


def test_summary_caps_failures_at_twenty():
    service = USMarketDataSyncService(
        symbol_repository=MagicMock(), stock_repository=MagicMock(), router=MagicMock(),
        config=DataProviderConfig(), now=datetime(2026, 7, 2, 22, tzinfo=timezone.utc),
    )
    from finance_analysis.tasks.celery.jobs.us_market_data_sync.models import DataTypeResult, SymbolResult

    results = [SymbolResult(f"S{i}.US", DataTypeResult("failed", "repair", reason="x")) for i in range(25)]
    summary = service._summarize(results, 25)
    assert summary["failure_count"] == 25
    assert summary["failures_truncated"] is True
    assert len(summary["failures"]) == 20


def test_three_minute_trading_days_create_exactly_three_request_units():
    stock_repo = MagicMock()
    stock_repo.has_minute_data.return_value = False
    stock_repo.upsert_minute.return_value = UpsertStats(inserted_rows=1)
    router = MagicMock()

    def route(symbol, trading_day, now=None):
        row = {
            "bar_time": datetime.combine(trading_day, datetime.min.time(), tzinfo=timezone.utc),
            "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1, "amount": None,
        }
        return RoutedBars([ProviderBars("LongbridgeFetcher", 100, [row])], [], ["LongbridgeFetcher"], str(trading_day))

    router.fetch_minute_day.side_effect = route
    service = USMarketDataSyncService(
        symbol_repository=MagicMock(), stock_repository=stock_repo, router=router,
        config=DataProviderConfig(market_data_initial_minute_days=3),
        now=datetime(2026, 7, 2, 22, tzinfo=timezone.utc),
    )
    result = service._sync_minute(_symbol())
    assert result.status == "success"
    assert router.fetch_minute_day.call_count == 3


def test_all_symbols_failed_raises_task_level_error():
    from finance_analysis.tasks.celery.jobs.us_market_data_sync.models import DataTypeResult, SymbolResult
    from finance_analysis.tasks.celery.jobs.us_market_data_sync.service import USMarketDataSyncError

    symbols = MagicMock()
    symbols.list_enabled_symbols.return_value = [_symbol()]
    service = USMarketDataSyncService(
        symbol_repository=symbols, stock_repository=MagicMock(), router=MagicMock(),
        config=DataProviderConfig(), now=datetime(2026, 7, 2, 22, tzinfo=timezone.utc),
    )
    service._sync_symbol = MagicMock(
        return_value=SymbolResult("AAPL.US", DataTypeResult("failed", "repair"), DataTypeResult("failed", "repair"))
    )
    with pytest.raises(USMarketDataSyncError, match="All 1 US symbols failed"):
        service.run()


@pytest.mark.skipif(not __import__("os").getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_seed_and_priority_conditioned_postgresql_upsert():
    db = DatabaseManager.get_instance()
    symbols = MarketDataSymbolRepository(db)
    stock = StockRepository(db)
    assert len(symbols.list_enabled_symbols("US")) == 101
    apple = symbols.get_by_code("AAPL.US")
    day = date(2040, 1, 3)
    with db._engine.begin() as connection:
        connection.execute(text("DELETE FROM stock_daily WHERE symbol_id=:id AND date=:day"), {"id": apple.id, "day": day})
    try:
        assert stock.upsert_daily(apple.id, [_daily(day, 10)], "YfinanceFetcher", 50).inserted_rows == 1
        low = stock.upsert_daily(apple.id, [_daily(day, 9)], "lower", 10)
        assert low.skipped_lower_priority_rows == 1
        high = stock.upsert_daily(apple.id, [_daily(day, 11)], "LongbridgeFetcher", 100)
        assert high.updated_rows == 1
        row = stock.get_range("AAPL.US", day, day)[0]
        assert row.close == 11
        assert row.data_source == "LongbridgeFetcher"
        assert row.amount is None
    finally:
        with db._engine.begin() as connection:
            connection.execute(text("DELETE FROM stock_daily WHERE symbol_id=:id AND date=:day"), {"id": apple.id, "day": day})


@pytest.mark.skipif(not __import__("os").getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_database_schema_constraints_and_active_task_dedupe_index_exist():
    db = DatabaseManager.get_instance()
    db_inspector = inspect(db._engine)
    assert "market_data_symbol" in db_inspector.get_table_names()
    assert "stock_minute" in db_inspector.get_table_names()
    indexes = {item["name"] for item in db_inspector.get_indexes("task")}
    assert "uix_task_active_dedupe" in indexes


@pytest.mark.skipif(not __import__("os").getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_duplicate_sync_task_is_persisted_as_skipped_without_calling_job():
    from finance_analysis.database.repositories.task_record import TaskRecordRepository
    from finance_analysis.tasks.lifecycle import TaskLifecycleService, track_task

    db = DatabaseManager.get_instance()
    repository = TaskRecordRepository(db)
    key = "market_data_sync_us:test-dedupe"
    with db._engine.begin() as connection:
        connection.execute(text("DELETE FROM task WHERE dedupe_key=:key OR task_id IN ('sync-owner','sync-duplicate')"), {"key": key})
    repository.ensure_record(
        task_id="sync-owner", task_type="scheduled_us_market_data_sync", task_name="sync",
        source="celery", status="processing", dedupe_key=key,
    )
    called = MagicMock()

    @track_task(
        task_type="scheduled_us_market_data_sync", task_name="sync", source="celery",
        strip_lifecycle_kwargs=True, dedupe_key=key,
    )
    def job():
        called()
        return {"sync_status": "success"}

    service = TaskLifecycleService(repository)
    try:
        with patch("finance_analysis.tasks.lifecycle.get_task_lifecycle_service", return_value=service):
            assert job(task_id="sync-duplicate") is None
        called.assert_not_called()
        duplicate = repository.get_by_task_id("sync-duplicate")
        assert duplicate.status == "skipped"
    finally:
        with db._engine.begin() as connection:
            connection.execute(text("DELETE FROM task WHERE task_id IN ('sync-owner','sync-duplicate')"))


@pytest.mark.skipif(not __import__("os").getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_partial_result_is_recorded_as_completed():
    import json

    from finance_analysis.database.repositories.task_record import TaskRecordRepository
    from finance_analysis.tasks.lifecycle import TaskLifecycleService, track_task

    db = DatabaseManager.get_instance()
    repository = TaskRecordRepository(db)
    with db._engine.begin() as connection:
        connection.execute(text("DELETE FROM task WHERE task_id='sync-partial'"))

    @track_task(
        task_type="scheduled_us_market_data_sync", task_name="sync", source="celery",
        strip_lifecycle_kwargs=True, record_result=True,
    )
    def job():
        return {"sync_status": "partial", "failure_count": 1}

    try:
        with patch(
            "finance_analysis.tasks.lifecycle.get_task_lifecycle_service",
            return_value=TaskLifecycleService(repository),
        ):
            assert job(task_id="sync-partial")["sync_status"] == "partial"
        record = repository.get_by_task_id("sync-partial")
        assert record.status == "completed"
        assert json.loads(record.result)["sync_status"] == "partial"
    finally:
        with db._engine.begin() as connection:
            connection.execute(text("DELETE FROM task WHERE task_id='sync-partial'"))

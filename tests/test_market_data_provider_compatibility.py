"""Offline compatibility contracts for optional market-data SDKs."""

from datetime import datetime, timezone
from importlib.metadata import version
from types import SimpleNamespace
from unittest.mock import patch

import akshare
import baostock
import longbridge
import pandas as pd
import pytest
import tickflow
import yfinance
from packaging.version import Version

from finance_analysis.integrations.market_data.base import DataFetchError, STANDARD_COLUMNS
from finance_analysis.integrations.market_data.providers.akshare import AkshareFetcher
from finance_analysis.integrations.market_data.providers.baostock import BaostockFetcher, _result_to_dataframe
from finance_analysis.integrations.market_data.providers.yfinance import YfinanceFetcher


@pytest.mark.parametrize(
    ("package", "module", "minimum"),
    [
        ("longbridge", longbridge, "4.3.3"),
        ("akshare", akshare, "1.18.64"),
        ("baostock", baostock, "0.9.3"),
        ("yfinance", yfinance, "1.5.1"),
        ("tickflow", tickflow, "0.1.24"),
    ],
)
def test_provider_dependency_imports_and_minimum_versions(package, module, minimum):
    assert module is not None
    assert Version(version(package)) >= Version(minimum)


def test_longbridge_433_public_contract_used_by_adapters_is_available():
    from longbridge.openapi import (
        AdjustType,
        AsyncQuoteContext,
        CalendarContext,
        Config,
        ContentContext,
        Period,
        QuoteContext,
        SubType,
        TradeSessions,
    )

    assert callable(Config.from_apikey)
    assert callable(Config.from_apikey_env)
    for method in (
        "quote",
        "static_info",
        "security_list",
        "trading_days",
        "candlesticks",
        "history_candlesticks_by_offset",
        "filings",
        "subscribe",
        "unsubscribe",
    ):
        assert callable(getattr(QuoteContext, method))
    assert callable(AsyncQuoteContext.create)
    assert callable(ContentContext.news)
    assert callable(CalendarContext.finance_calendar)
    assert Period.Day is not None
    assert AdjustType.NoAdjust is not None
    assert TradeSessions.All is not None
    assert SubType.Quote is not None


def test_akshare_normalizer_stabilizes_schema_and_numeric_types():
    raw = pd.DataFrame(
        {
            "日期": ["2026-07-09"],
            "开盘": ["10.1"],
            "最高": ["10.8"],
            "最低": ["9.9"],
            "收盘": ["10.5"],
            "成交量": ["1200"],
        }
    )
    fetcher = AkshareFetcher()

    normalized = fetcher._clean_data(fetcher._normalize_data(raw, "600519"))

    assert list(normalized.columns) == ["code"] + STANDARD_COLUMNS
    assert normalized.loc[0, "date"] == pd.Timestamp("2026-07-09")
    assert normalized.loc[0, "close"] == pytest.approx(10.5)
    assert normalized.loc[0, "volume"] == pytest.approx(1200)
    assert pd.isna(normalized.loc[0, "amount"])
    assert pd.isna(normalized.loc[0, "pct_chg"])


def test_akshare_normalizer_handles_empty_and_rejects_missing_critical_columns():
    fetcher = AkshareFetcher()
    empty = fetcher._normalize_data(pd.DataFrame(), "600519")
    assert list(empty.columns) == ["code"] + STANDARD_COLUMNS

    with pytest.raises(DataFetchError, match="缺少必要字段: high, low, open, volume"):
        fetcher._normalize_data(pd.DataFrame({"日期": ["2026-07-09"], "收盘": [10]}), "600519")


def test_akshare_tencent_fallback_treats_upstream_amount_as_volume():
    raw = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-07-09").date()],
            "open": [10.1],
            "close": [10.5],
            "high": [10.8],
            "low": [9.9],
            "amount": [1200],
        }
    )
    fetcher = AkshareFetcher()

    with patch.object(fetcher, "_enforce_rate_limit"), patch("akshare.stock_zh_a_hist_tx", return_value=raw):
        fallback = fetcher._fetch_stock_data_tx("600519", "2026-07-09", "2026-07-09")
    normalized = fetcher._normalize_data(fallback, "600519")

    assert normalized.loc[0, "volume"] == 1200
    assert pd.isna(normalized.loc[0, "amount"])


def test_akshare_market_stats_returns_none_for_changed_upstream_schema():
    fetcher = AkshareFetcher()
    assert fetcher._calc_market_stats(pd.DataFrame({"代码": ["600519"], "名称": ["贵州茅台"]})) is None


class _BaostockCursor:
    error_code = "0"
    error_msg = "success"
    fields = ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"]

    def __init__(self, rows):
        self._rows = iter(rows)
        self._current = None

    def next(self):
        self._current = next(self._rows, None)
        return self._current is not None

    def get_row_data(self):
        return self._current


def test_baostock_cursor_and_string_values_are_normalized():
    row = ["2026-07-09", "10.1", "10.8", "9.9", "10.5", "1200", "12600", "2.1"]
    frame = _result_to_dataframe(_BaostockCursor([row]))
    normalized = BaostockFetcher()._normalize_data(frame, "600519")

    assert list(normalized.columns) == ["code"] + STANDARD_COLUMNS
    assert normalized.loc[0, "close"] == pytest.approx(10.5)
    assert normalized.loc[0, "pct_chg"] == pytest.approx(2.1)


def test_baostock_cursor_rejects_changed_row_shape():
    with pytest.raises(DataFetchError, match="字段数量不匹配"):
        _result_to_dataframe(_BaostockCursor([["2026-07-09", "10.1"]]))


def test_baostock_session_logs_out_when_query_raises():
    class FakeBaostock:
        def __init__(self):
            self.logout_calls = 0

        def login(self):
            return SimpleNamespace(error_code="0", error_msg="success")

        def logout(self):
            self.logout_calls += 1
            return SimpleNamespace(error_code="0", error_msg="success")

    sdk = FakeBaostock()
    fetcher = BaostockFetcher()
    fetcher._bs_module = sdk

    with pytest.raises(RuntimeError, match="query failed"):
        with fetcher._baostock_session():
            raise RuntimeError("query failed")

    assert sdk.logout_calls == 1


def test_yfinance_multiindex_normalization_preserves_business_schema():
    columns = pd.MultiIndex.from_tuples(
        [(name, "AAPL") for name in ("Open", "High", "Low", "Close", "Volume")]
    )
    raw = pd.DataFrame(
        [[190.0, 195.0, 189.0, 194.0, 1000]],
        index=pd.DatetimeIndex(["2026-07-09"], name="Date"),
        columns=columns,
    )

    normalized = YfinanceFetcher()._normalize_data(raw, "AAPL")

    assert list(normalized.columns) == ["code"] + STANDARD_COLUMNS
    assert normalized.loc[0, "date"] == pd.Timestamp("2026-07-09")
    assert normalized.loc[0, "close"] == pytest.approx(194.0)
    assert normalized.loc[0, "pct_chg"] == 0
    assert normalized.loc[0, "amount"] is None


def test_yfinance_minute_download_keeps_regular_session_and_converts_to_utc():
    raw = pd.DataFrame(
        {"Open": [190.0], "High": [195.0], "Low": [189.0], "Close": [194.0], "Volume": [1000]},
        index=pd.DatetimeIndex(["2026-07-09 09:30:00-04:00"], name="Datetime"),
    )
    symbol = SimpleNamespace(code="AAPL.US", market="US")

    with patch("yfinance.download", return_value=raw) as download:
        frame = YfinanceFetcher()._download_history(
            symbol,
            start=datetime(2026, 7, 9, 13, 30, tzinfo=timezone.utc),
            end=datetime(2026, 7, 9, 13, 31, tzinfo=timezone.utc),
            interval="1m",
            data_type="minute",
        )

    assert download.call_args.kwargs["auto_adjust"] is False
    assert download.call_args.kwargs["prepost"] is False
    assert download.call_args.kwargs["multi_level_index"] is False
    assert frame.loc[0, "bar_time"] == pd.Timestamp("2026-07-09 13:30:00+00:00")
    assert frame.loc[0, "amount"] is None


def test_yfinance_normalizer_handles_empty_and_rejects_missing_critical_columns():
    fetcher = YfinanceFetcher()
    empty = fetcher._normalize_data(pd.DataFrame(), "AAPL")
    assert list(empty.columns) == ["code"] + STANDARD_COLUMNS

    raw = pd.DataFrame({"Close": [194.0]}, index=pd.DatetimeIndex(["2026-07-09"], name="Date"))
    with pytest.raises(DataFetchError, match="缺少必要字段"):
        fetcher._normalize_data(raw, "AAPL")

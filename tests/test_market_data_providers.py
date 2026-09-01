from datetime import date
from types import SimpleNamespace

import pandas as pd

from finance_analysis.integrations.market_data.models import Adjustment, DailyBarsRequest
from finance_analysis.integrations.market_data.providers.baostock import BaoStockProvider
from finance_analysis.integrations.market_data.providers.pytdx import PyTDXProvider
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider


class _BaoCursor:
    error_code = "0"
    error_msg = ""
    fields = ["date", "open", "high", "low", "close", "volume", "amount"]

    def __init__(self):
        self._done = False

    def next(self):
        if self._done:
            return False
        self._done = True
        return True

    def get_row_data(self):
        return ["2025-01-02", "10", "11", "9", "10.5", "100", "1050"]


def test_baostock_reuses_login_and_always_requests_forward_adjusted_bars():
    calls = []

    class _SDK:
        login_count = 0

        def login(self):
            self.login_count += 1
            return SimpleNamespace(error_code="0", error_msg="")

        def query_history_k_data_plus(self, symbol, fields, **kwargs):
            calls.append((symbol, kwargs))
            return _BaoCursor()

        def logout(self):
            return None

    sdk = _SDK()
    provider = BaoStockProvider(sdk=sdk)
    result = provider.fetch_daily_bars(
        DailyBarsRequest(
            ("600000.SH", "000001.SZ"), date(2025, 1, 1), date(2025, 1, 3), Adjustment.FORWARD
        )
    )

    assert sdk.login_count == 1
    assert set(result.data) == {"600000.SH", "000001.SZ"}
    assert [kwargs["adjustflag"] for _, kwargs in calls] == ["2", "2"]


def test_pytdx_reuses_injected_connection_and_converts_lots_to_shares():
    class _API:
        calls = []

        def get_security_bars(self, category, market, code, offset, count):
            self.calls.append((category, market, code, offset, count))
            if offset:
                return []
            return [{"datetime": "2025-01-02", "open": 10, "high": 11, "low": 9,
                     "close": 10.5, "vol": 123, "amount": 129150}]

        @staticmethod
        def to_df(rows):
            return pd.DataFrame(rows)

    api = _API()
    result = PyTDXProvider(api=api).fetch_daily_bars(
        DailyBarsRequest(("600000.SH", "000001.SZ"), date(2025, 1, 1), date(2025, 1, 3), Adjustment.RAW)
    )

    assert len(api.calls) == 2
    assert result.data["600000.SH"][0].volume == 12300
    assert result.data["000001.SZ"][0].volume == 12300


def test_yfinance_daily_download_enables_auto_adjust_without_actions(monkeypatch):
    captured = {}

    def download(**kwargs):
        captured.update(kwargs)
        frame = pd.DataFrame(
            {"Open": [10], "High": [11], "Low": [9], "Close": [10.5], "Volume": [100]},
            index=pd.DatetimeIndex(["2025-01-02"], name="Date"),
        )
        frame.columns = pd.MultiIndex.from_product([["AAPL"], frame.columns])
        return frame

    monkeypatch.setattr("yfinance.download", download)
    result = YFinanceProvider().fetch_daily_bars(
        DailyBarsRequest(("AAPL.US",), date(2025, 1, 1), date(2025, 1, 3), Adjustment.FORWARD)
    )

    assert result.data["AAPL.US"][0].amount is None
    assert captured["auto_adjust"] is True
    assert captured["actions"] is False
    assert result.data["AAPL.US"][0].adjustment is Adjustment.FORWARD


def test_yfinance_daily_download_batches_ten_us_symbols_once_with_threads(monkeypatch):
    calls = []
    symbols = tuple(f"US{index}.US" for index in range(10))
    provider_symbols = [f"US{index}" for index in range(10)]

    def download(**kwargs):
        calls.append(kwargs)
        frames = {
            ticker: pd.DataFrame(
                {"Open": [10], "High": [11], "Low": [9], "Close": [10.5], "Volume": [100]},
                index=pd.DatetimeIndex(["2025-01-02"], name="Date"),
            )
            for ticker in provider_symbols
        }
        return pd.concat(frames, axis=1)

    monkeypatch.setattr("yfinance.download", download)
    result = YFinanceProvider().fetch_daily_bars(
        DailyBarsRequest(symbols, date(2025, 1, 1), date(2025, 1, 3), Adjustment.FORWARD)
    )

    assert len(calls) == 1
    assert calls[0]["tickers"] == provider_symbols
    assert calls[0]["threads"] == 3
    assert calls[0]["auto_adjust"] is True
    assert set(result.data) == set(symbols)


def test_yfinance_daily_download_splits_batches_and_retries_only_missing_symbols(monkeypatch):
    calls = []

    def frame_for(tickers):
        frames = {
            ticker: pd.DataFrame(
                {"Open": [10], "High": [11], "Low": [9], "Close": [10.5], "Volume": [100]},
                index=pd.DatetimeIndex(["2025-01-02"], name="Date"),
            )
            for ticker in tickers
        }
        return pd.concat(frames, axis=1) if frames else pd.DataFrame()

    def download(**kwargs):
        tickers = list(kwargs["tickers"])
        calls.append(tickers)
        if tickers == ["AAPL", "MSFT"]:
            return frame_for(["AAPL"])
        return frame_for(tickers)

    monkeypatch.setattr("yfinance.download", download)
    provider = YFinanceProvider(batch_size=2, max_workers=1, max_retries=1)
    result = provider.fetch_daily_bars(
        DailyBarsRequest(
            ("AAPL.US", "MSFT.US", "NVDA.US"),
            date(2025, 1, 1),
            date(2025, 1, 3),
            Adjustment.FORWARD,
        )
    )

    assert calls == [["AAPL", "MSFT"], ["MSFT"], ["NVDA"]]
    assert set(result.data) == {"AAPL.US", "MSFT.US", "NVDA.US"}
    assert result.missing_symbols == []
    assert result.failed_symbols == {}

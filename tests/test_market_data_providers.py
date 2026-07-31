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


def test_baostock_reuses_login_and_always_requests_unadjusted_bars():
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
        DailyBarsRequest(("600000.SH", "000001.SZ"), date(2025, 1, 1), date(2025, 1, 3), Adjustment.RAW)
    )

    assert sdk.login_count == 1
    assert set(result.data) == {"600000.SH", "000001.SZ"}
    assert [kwargs["adjustflag"] for _, kwargs in calls] == ["3", "3"]


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


def test_yfinance_daily_download_disables_auto_adjust_and_requests_actions(monkeypatch):
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
        DailyBarsRequest(("AAPL.US",), date(2025, 1, 1), date(2025, 1, 3), Adjustment.RAW)
    )

    assert result.data["AAPL.US"][0].amount is None
    assert captured["auto_adjust"] is False
    assert captured["actions"] is True

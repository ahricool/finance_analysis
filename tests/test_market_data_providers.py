from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.models import Adjustment, DailyBarsRequest
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider


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
    events = []
    monkeypatch.setattr("finance_analysis.integrations.market_data.batch_pacing.sleep", events.append)

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
        events.append(tickers)
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
    assert events == [["AAPL", "MSFT"], ["MSFT"], 10, ["NVDA"]]
    assert set(result.data) == {"AAPL.US", "MSFT.US", "NVDA.US"}
    assert result.missing_symbols == []
    assert result.failed_symbols == {}


@pytest.fixture(autouse=True)
def mock_daily_sync_waits(monkeypatch):
    monkeypatch.setattr("finance_analysis.integrations.market_data.batch_pacing.sleep", lambda seconds: None)
    monkeypatch.setattr("finance_analysis.tasks.celery.jobs.market_data_sync.service.sleep", lambda seconds: None)

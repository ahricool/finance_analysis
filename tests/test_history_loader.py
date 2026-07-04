from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from finance_analysis.analysis.history.errors import HistoricalMarketDataMissingError
from finance_analysis.analysis.history.loader import (
    load_history_df,
    reset_frozen_target_date,
    set_frozen_target_date,
)


def _bar(day: date, close: float = 10.0):
    payload = {
        "code": "AAPL.US", "market": "US", "date": day,
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": 100.0, "amount": None, "data_source": "test", "source_priority": 100,
    }
    return SimpleNamespace(date=day, to_dict=lambda: payload)


def test_loader_reads_complete_database_window_and_derives_indicators():
    days = [date(2026, 4, 13) + timedelta(days=i) for i in range(5)]
    repo = MagicMock()
    repo.get_range.return_value = [_bar(day, 10 + i) for i, day in enumerate(days)]
    with patch("finance_analysis.analysis.history.loader.get_completed_trading_days", return_value=days), \
         patch("finance_analysis.database.repositories.stock.StockRepository", return_value=repo):
        frame, source = load_history_df("AAPL.US", days=5, target_date=days[-1])
    assert source == "database"
    assert len(frame) == 5
    assert frame.iloc[-1]["ma5"] == pytest.approx(12.0)
    assert "pct_chg" in frame
    repo.get_range.assert_called_once_with("AAPL.US", days[0], days[-1])


def test_loader_raises_explicit_missing_error_without_network_fallback():
    days = [date(2026, 4, 13), date(2026, 4, 14)]
    repo = MagicMock()
    repo.get_range.return_value = [_bar(days[0])]
    with patch("finance_analysis.analysis.history.loader.get_completed_trading_days", return_value=days), \
         patch("finance_analysis.database.repositories.stock.StockRepository", return_value=repo):
        with pytest.raises(HistoricalMarketDataMissingError) as error:
            load_history_df("AAPL.US", days=2, target_date=days[-1])
    assert error.value.market == "US"
    assert error.value.code == "AAPL.US"
    assert error.value.missing_count == 1
    assert error.value.latest_available == days[0]


@pytest.mark.parametrize("legacy", ["AAPL", "HK00700", "00700", "0700.HK", "SH600519"])
def test_loader_rejects_legacy_symbol_formats(legacy):
    with pytest.raises(ValueError, match="ticker.region"):
        load_history_df(legacy, days=1)


def test_loader_uses_frozen_target_date():
    target = date(2026, 4, 15)
    repo = MagicMock()
    repo.get_range.return_value = [_bar(target)]
    token = set_frozen_target_date(target)
    try:
        with patch("finance_analysis.analysis.history.loader.get_completed_trading_days", return_value=[target]) as calendar, \
             patch("finance_analysis.database.repositories.stock.StockRepository", return_value=repo):
            load_history_df("AAPL.US", days=1)
        assert calendar.call_args.args[:2] == ("us", 1)
        assert calendar.call_args.args[2].date() == target
    finally:
        reset_frozen_target_date(token)

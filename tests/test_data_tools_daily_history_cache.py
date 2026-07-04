from datetime import date
from unittest.mock import patch

import pandas as pd

from finance_analysis.agent.tools.data_tools import _handle_get_daily_history
from finance_analysis.analysis.history.errors import HistoricalMarketDataMissingError


def test_agent_history_tool_reads_database_only():
    frame = pd.DataFrame(
        [{"code": "AAPL.US", "date": date(2026, 7, 2), "open": 1, "high": 2,
          "low": 0.5, "close": 1.5, "volume": 10, "ma5": 1.4, "ma10": 1.3, "ma20": 1.2}]
    )
    with patch("finance_analysis.analysis.history.loader.load_history_df", return_value=(frame, "database")):
        response = _handle_get_daily_history("AAPL.US", 1)
    assert response["source"] == "database"
    assert response["cache_hit"] is True
    assert response["partial_cache"] is False
    assert response["data"][0]["date"] == "2026-07-02"


def test_agent_history_tool_reports_database_gap_without_fetch_or_persist():
    error = HistoricalMarketDataMissingError(
        "US", "AAPL.US", "1d", date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 1),
        (date(2026, 7, 2),), 1,
    )
    with patch("finance_analysis.analysis.history.loader.load_history_df", side_effect=error):
        response = _handle_get_daily_history("AAPL.US", 2)
    assert "Historical market data missing" in response["error"]


def test_agent_history_days_are_bounded():
    frame = pd.DataFrame(
        [{"code": "AAPL.US", "date": date(2026, 7, 2), "close": 1.5, "volume": 1}]
    )
    with patch("finance_analysis.analysis.history.loader.load_history_df", return_value=(frame, "database")) as loader:
        response = _handle_get_daily_history("AAPL.US", 99999)
    assert response["effective_days"] < 99999
    assert "warning" in response
    assert loader.call_args.kwargs["days"] == response["effective_days"]

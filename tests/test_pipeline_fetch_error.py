# -*- coding: utf-8 -*-
"""Regression tests for pipeline data-fetch error handling."""

from datetime import date, datetime, timezone
import unittest
from unittest.mock import MagicMock, patch

from finance_analysis.analysis.pipeline import StockAnalysisPipeline


class PipelineFetchErrorTestCase(unittest.TestCase):
    """`fetch_and_save_stock_data` should preserve the original exception."""

    def test_fetch_and_save_reports_database_history_failure(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        with patch(
            "finance_analysis.analysis.history.loader.load_history_df",
            side_effect=RuntimeError("database history missing"),
        ):
            success, error = StockAnalysisPipeline.fetch_and_save_stock_data(pipeline, "600519.SH")

        self.assertFalse(success)
        self.assertIn("database history missing", error or "")
        pipeline.fetcher_manager.get_daily_data.assert_not_called()

    @patch.object(
        StockAnalysisPipeline,
        "_resolve_resume_target_date",
        return_value=date(2026, 3, 27),
    )
    def test_fetch_and_save_uses_effective_trading_date_for_resume_check(self, _mock_target):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        current_time = datetime(2026, 3, 28, 1, 0, tzinfo=timezone.utc)

        with patch("finance_analysis.analysis.history.loader.load_history_df", return_value=(MagicMock(), "database")) as loader:
            success, error = StockAnalysisPipeline.fetch_and_save_stock_data(
                pipeline,
                "600519.SH",
                current_time=current_time,
            )

        self.assertTrue(success)
        self.assertIsNone(error)
        _mock_target.assert_called_once_with("600519.SH", current_time=current_time)
        loader.assert_called_once_with("600519.SH", days=30, target_date=date(2026, 3, 27))
        pipeline.fetcher_manager.get_daily_data.assert_not_called()

    def test_resolve_resume_target_date_accepts_canonical_formats_only(self):
        with patch("finance_analysis.analysis.pipeline.get_market_for_stock", return_value="cn") as mock_market, patch(
            "finance_analysis.analysis.pipeline.get_effective_trading_date",
            return_value=date(2026, 3, 27),
        ) as mock_target:
            for code in ("600519.SH", "000001.SZ", "AAPL.US"):
                result = StockAnalysisPipeline._resolve_resume_target_date(code)
                self.assertEqual(result, date(2026, 3, 27))

        self.assertEqual(
            [args.args[0] for args in mock_market.call_args_list],
            ["600519.SH", "000001.SZ", "AAPL.US"],
        )
        self.assertEqual(mock_target.call_count, 3)


if __name__ == "__main__":
    unittest.main()

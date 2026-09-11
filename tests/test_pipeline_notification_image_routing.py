"""Aggregate reports use the same persistence and delivery boundary as single reports."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from finance_analysis.analysis.pipeline import StockAnalysisPipeline
from finance_analysis.reporting.types import ReportType


def test_aggregate_uses_one_send_with_owner_and_stable_noise_keys():
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.notification_uid = 7
    pipeline.notifier = MagicMock()
    pipeline.notifier.generate_aggregate_report.return_value = "# aggregate"
    pipeline._send_notifications([SimpleNamespace(code="AAPL.US")], ReportType.BRIEF)
    pipeline.notifier.send.assert_called_once_with(
        "# aggregate",
        uid=7,
        route_type="report",
        severity="info",
        dedup_key="report:aggregate:brief:AAPL.US",
        cooldown_key="report:aggregate:brief:AAPL.US",
        push=True,
    )


def test_merge_and_single_modes_do_not_store_duplicate_aggregate():
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.notifier = MagicMock()
    pipeline._send_notifications([], skip_push=True)
    pipeline.notifier.send.assert_not_called()

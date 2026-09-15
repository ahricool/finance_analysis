"""Regression tests for pipeline progress callback failures."""

import logging

from finance_analysis.analysis.pipeline import StockAnalysisPipeline


def test_emit_progress_logs_context_when_callback_fails(caplog):
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.query_id = "query-123"

    def _fail_callback(progress, message):
        raise RuntimeError(f"cannot send {progress}:{message}")

    pipeline.progress_callback = _fail_callback

    with caplog.at_level(logging.WARNING, logger="finance_analysis.analysis.pipeline"):
        pipeline._emit_progress(55, "fetching news")

    records = [record for record in caplog.records if "progress callback failed" in record.message]
    assert len(records) == 1
    record = records[0]
    assert "progress=55" in record.message
    assert "message='fetching news'" in record.message
    assert "query_id=query-123" in record.message
    assert record.progress == 55
    assert record.progress_message == "fetching news"
    assert record.query_id == "query-123"

# -*- coding: utf-8 -*-
"""Regression tests for optional pipeline service degradation logs."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from finance_analysis.analysis.pipeline import StockAnalysisPipeline


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        max_workers=2,
        save_context_snapshot=False,
        enable_realtime_quote=False,
        enable_chip_distribution=False,
        social_sentiment_api_key="",
        social_sentiment_api_url="https://example.invalid/social",
    )


def _build_pipeline(config: SimpleNamespace) -> StockAnalysisPipeline:
    with patch("finance_analysis.analysis.pipeline.get_db", return_value=MagicMock()), \
         patch("finance_analysis.analysis.pipeline.MarketDataService", return_value=MagicMock()), \
         patch("finance_analysis.analysis.pipeline.StockTrendAnalyzer", return_value=MagicMock()), \
         patch("finance_analysis.analysis.pipeline.StockReportAnalyzer", return_value=MagicMock()), \
         patch("finance_analysis.analysis.pipeline.NotificationService", return_value=MagicMock()):
        return StockAnalysisPipeline(config=config, owner_uid=1)




def test_social_sentiment_init_failure_logs_traceback(caplog):
    config = _make_config()

    with patch("finance_analysis.analysis.pipeline.SocialSentimentService", side_effect=RuntimeError("social init boom")), \
         caplog.at_level(logging.WARNING, logger="finance_analysis.analysis.pipeline"):
        pipeline = _build_pipeline(config)

    assert pipeline.social_sentiment_service is None

    init_failure_records = [
        record for record in caplog.records if "社交舆情服务初始化失败，将跳过舆情分析" in record.message
    ]
    assert len(init_failure_records) == 1
    assert init_failure_records[0].exc_info is not None


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

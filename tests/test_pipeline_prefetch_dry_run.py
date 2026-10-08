# -*- coding: utf-8 -*-
"""
Regression tests for prefetch behavior in StockAnalysisPipeline.run().
"""

import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from finance_analysis.analysis.pipeline import StockAnalysisPipeline


class TestPipelinePrefetchBehavior(unittest.TestCase):
    @staticmethod
    def _build_pipeline(process_result):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.max_workers = 1
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.db.has_today_data.return_value = False
        pipeline.process_single_stock = MagicMock(return_value=process_result)
        pipeline.config = SimpleNamespace(
            single_stock_notify=False,
            report_type="simple",
            analysis_delay=0,
        )
        return pipeline

    def test_run_dry_run_skips_stock_name_prefetch(self):
        pipeline = self._build_pipeline(process_result=None)

        pipeline.run(stock_codes=["000001.SZ"], dry_run=True, send_notification=False)

        pipeline.fetcher_manager.get_instrument_info.assert_not_called()

    def test_run_non_dry_run_prefetches_stock_names(self):
        pipeline = self._build_pipeline(process_result=SimpleNamespace(code="000001.SZ"))

        pipeline.run(stock_codes=["000001.SZ"], dry_run=False, send_notification=False)

        pipeline.fetcher_manager.get_instrument_info.assert_called_once_with(["000001.SZ"])

    def test_run_dry_run_counts_existing_data_by_effective_trading_date(self):
        pipeline = self._build_pipeline(process_result=None)
        pipeline._resolve_resume_target_date = MagicMock(
            side_effect=[date(2026, 3, 27), date(2026, 3, 26)]
        )
        pipeline.db.has_today_data.side_effect = [True, False]

        pipeline.run(
            stock_codes=["600519.SH", "AAPL.US"],
            dry_run=True,
            send_notification=False,
        )

        self.assertEqual(
            pipeline.db.has_today_data.call_args_list,
            [
                call("600519.SH", date(2026, 3, 27)),
                call("AAPL.US", date(2026, 3, 26)),
            ],
        )

    def test_run_uses_one_frozen_reference_time_for_tasks_and_dry_run_stats(self):
        pipeline = self._build_pipeline(process_result=None)
        pipeline._resolve_resume_target_date = MagicMock(
            side_effect=[date(2026, 3, 27), date(2026, 3, 26)]
        )
        pipeline.db.has_today_data.side_effect = [True, False]

        pipeline.run(
            stock_codes=["600519.SH", "AAPL.US"],
            dry_run=True,
            send_notification=False,
        )

        task_reference_times = [
            call.kwargs["current_time"]
            for call in pipeline.process_single_stock.call_args_list
        ]
        stats_reference_times = [
            call.kwargs["current_time"]
            for call in pipeline._resolve_resume_target_date.call_args_list
        ]

        self.assertEqual(len(task_reference_times), 2)
        self.assertEqual(len(stats_reference_times), 2)
        self.assertEqual(len({id(value) for value in task_reference_times}), 1)
        self.assertEqual(len({id(value) for value in stats_reference_times}), 1)
        self.assertIs(task_reference_times[0], stats_reference_times[0])


if __name__ == "__main__":
    unittest.main()


class _PrefetchProvider:
    """Network-free provider behind the real service and routing validation."""

    def __init__(self):
        self.quote_requests = []
        self.instrument_requests = []

    def fetch_quotes(self, request):
        from finance_analysis.integrations.market_data.models import BatchQuoteResult
        self.quote_requests.append(request.symbols)
        return BatchQuoteResult()

    def get_instrument_info(self, request):
        from finance_analysis.integrations.market_data.models import BatchInstrumentResult
        self.instrument_requests.append(request.symbols)
        return BatchInstrumentResult()


def test_mixed_market_batch_uses_real_router_and_one_aggregate(monkeypatch):
    from finance_analysis.integrations.market_data import MarketDataService
    from finance_analysis.integrations.market_data.registry import (
        INSTRUMENT_INFO, REALTIME_QUOTES, ProviderRegistry,
    )
    from finance_analysis.integrations.market_data.normalizer import infer_market

    provider = _PrefetchProvider()
    registry = ProviderRegistry()
    registry.register("offline", provider, capabilities={INSTRUMENT_INFO, REALTIME_QUOTES})
    monkeypatch.setattr("finance_analysis.integrations.market_data.router.provider_order", lambda *_: ("offline",))
    pipeline = TestPipelinePrefetchBehavior._build_pipeline(process_result=None)
    pipeline.fetcher_manager = MarketDataService(registry=registry)
    pipeline.process_single_stock.side_effect = lambda code, **_: SimpleNamespace(code=code, success=True)
    pipeline._send_notifications = MagicMock()
    codes = ["600519.SH", "MSFT.US", "700.HK", "000001.SZ", "AAPL.US"]

    results = pipeline.run(stock_codes=codes, send_notification=False)

    expected = [("600519.SH", "000001.SZ"), ("MSFT.US", "AAPL.US"), ("700.HK",)]
    assert provider.quote_requests == expected
    assert provider.instrument_requests == expected
    assert all(len({infer_market(code) for code in batch}) == 1 for batch in expected)
    assert {result.code for result in results} == set(codes)
    assert pipeline.process_single_stock.call_count == len(codes)
    pipeline._send_notifications.assert_called_once()
    assert pipeline._send_notifications.call_args.args[0] is results
    assert pipeline._send_notifications.call_args.kwargs == {"push": False}


def test_small_mixed_market_batch_prefetches_names_only(monkeypatch):
    from finance_analysis.integrations.market_data import MarketDataService
    from finance_analysis.integrations.market_data.registry import (
        INSTRUMENT_INFO, REALTIME_QUOTES, ProviderRegistry,
    )

    provider = _PrefetchProvider()
    registry = ProviderRegistry()
    registry.register("offline", provider, capabilities={INSTRUMENT_INFO, REALTIME_QUOTES})
    monkeypatch.setattr("finance_analysis.integrations.market_data.router.provider_order", lambda *_: ("offline",))
    pipeline = TestPipelinePrefetchBehavior._build_pipeline(process_result=None)
    pipeline.fetcher_manager = MarketDataService(registry=registry)
    pipeline.run(stock_codes=["600519.SH", "MSFT.US"], send_notification=False)
    assert provider.instrument_requests == [("600519.SH",), ("MSFT.US",)]
    assert provider.quote_requests == []

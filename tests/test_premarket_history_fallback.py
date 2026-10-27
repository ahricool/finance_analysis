"""Premarket reads complete DB/API history without writes and isolates stock failures."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from finance_analysis.analysis.history.prepared import load_analysis_history, prepared_history, analysis_context
from finance_analysis.analysis.pipeline import StockAnalysisPipeline
from finance_analysis.analysis.stock_report_analyzer import AnalysisResult
from finance_analysis.integrations.market_data.models import BatchBarResult, MarketBar, Market, Adjustment
from finance_analysis.integrations.market_data.service import MarketDataService

DAY = date(2026, 10, 23)
DAYS = [DAY - timedelta(days=i) for i in range(59, -1, -1)]


def bar(day, code="TSM.US"):
    return MarketBar(code, Market.US, "1d", day, None, 10, 12, 9, 11, 100, None, "USD", Adjustment.FORWARD, "test")


@pytest.mark.parametrize("mode", ["complete", "stale", "empty", "gap"])
def test_existing_facade_handles_complete_stale_empty_and_gapped_db(monkeypatch, mode):
    monkeypatch.setattr("finance_analysis.analysis.history.prepared.get_completed_trading_days", lambda *a: DAYS)
    monkeypatch.setattr("finance_analysis.integrations.market_data.service.get_completed_trading_days", lambda *a: [DAY])
    rows = [SimpleNamespace(date=d, instrument=SimpleNamespace(code="TSM.US", market="US"),
                            open=10, high=12, low=9, close=11, volume=100, amount=None) for d in DAYS]
    stored = {"complete": rows, "stale": rows[:-1], "empty": [], "gap": rows[:5] + rows[6:]}[mode]
    service = MarketDataService.__new__(MarketDataService)
    stocks = Mock()
    stocks.get_daily_ranges.return_value = {"TSM.US": stored}
    service._repositories = Mock(return_value=(Mock(), stocks))
    service.router = Mock()
    service.router.route_daily.return_value = BatchBarResult(data={"TSM.US": [bar(d) for d in DAYS]})
    frame = load_analysis_history(service, "TSM.US", DAY)
    assert len(frame) == 60 and frame.iloc[-1]["date"] == DAY
    if mode == "complete":
        service.router.route_daily.assert_not_called()
    else:
        request = service.router.route_daily.call_args.args[0]
        assert request.required_dates == tuple(DAYS)
        assert request.adjustment == Adjustment.FORWARD
    assert all(call[0] == "get_daily_ranges" for call in stocks.method_calls)


def pipeline():
    p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    p.allow_history_fallback = True
    p.query_id = None
    p.owner_uid = 1
    p.save_context_snapshot = False
    p.max_workers = 2
    p.config = SimpleNamespace(single_stock_notify=False, report_type="simple", analysis_delay=0)
    p.fetcher_manager = Mock()
    p._resolve_resume_target_date = Mock(return_value=DAY)
    p.notifier = Mock()
    p.notifier.generate_aggregate_report.return_value = "成功报告"
    return p


def success(code):
    return AnalysisResult(code, code, 50, "", "", success=True)


@pytest.mark.parametrize("all_failed", [False, True])
def test_failed_stock_does_not_block_others_and_is_reported(monkeypatch, all_failed):
    monkeypatch.setattr("finance_analysis.analysis.history.prepared.get_completed_trading_days", lambda *a: DAYS)
    p = pipeline()
    def fetch(symbols, *args, **kwargs):
        code = symbols[0]
        return BatchBarResult(data={} if code == "BAD.US" or all_failed else {code: [bar(d, code) for d in DAYS]})
    p.fetcher_manager.get_daily_bars.side_effect = fetch
    def analyze(code, *args, **kwargs):
        frame = prepared_history.get()
        assert frame.iloc[-1]["date"] == DAY
        assert set(frame["code"]) == {code}
        assert analysis_context(code, frame)["date"] == DAY.isoformat()
        return success(code)
    p.analyze_stock = Mock(side_effect=analyze)
    results = p.run(["TSM.US", "BAD.US"])
    assert len(results) == (0 if all_failed else 1)
    assert len(p.failures) == (2 if all_failed else 1)
    assert all("日K数据不足" in item["reason"] for item in p.failures)
    assert p.analyze_stock.call_count == (0 if all_failed else 1)
    assert "BAD.US" in p.notifier.send.call_args.args[0]
    assert prepared_history.get() is None


def test_premarket_task_enables_fallback_and_returns_failures(monkeypatch):
    from finance_analysis.tasks.celery.jobs.us_premarket_analysis.service import USPremarketAnalysisTaskService
    fake = Mock(failures=[{"code": "BAD.US", "reason": "日K缺失"}])
    fake.run.return_value = [success("TSM.US")]
    factory = Mock(return_value=fake)
    monkeypatch.setattr("finance_analysis.analysis.pipeline.StockAnalysisPipeline", factory)
    monkeypatch.setattr("finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market",
                        lambda market: ["TSM.US", "BAD.US"])
    result = USPremarketAnalysisTaskService().run()
    assert factory.call_args.kwargs["allow_history_fallback"] is True
    assert result["failed_count"] == 1 and result["failures"] == fake.failures


def test_real_analysis_uses_prepared_history_for_trend_and_llm_context(monkeypatch):
    monkeypatch.setattr("finance_analysis.analysis.history.prepared.get_completed_trading_days", lambda *a: DAYS)
    for name in ("fill_price_position_if_needed", "stabilize_decision_with_structure"):
        monkeypatch.setattr("finance_analysis.analysis.pipeline." + name, lambda *args: None)
    p = pipeline()
    p.config.enable_realtime_quote = False
    p.db = Mock()
    p.db.get_data_range.side_effect = AssertionError("must not reread stale DB")
    p.db.get_analysis_context.side_effect = AssertionError("must not reread stale context")
    p.fetcher_manager.get_daily_bars.return_value = BatchBarResult(data={"TSM.US": [bar(d) for d in DAYS]})
    p.fetcher_manager.get_instrument_info.return_value = SimpleNamespace(data={})
    p.fetcher_manager.get_fundamental_context.return_value = {}
    p.trend_analyzer = Mock()
    p.trend_analyzer.analyze.return_value = None
    p._enhance_context = lambda context, *args: context
    p.analyzer = Mock()
    p.analyzer.analyze.return_value = success("TSM.US")
    result = p.process_single_stock("TSM.US")
    assert result.success
    context = p.analyzer.analyze.call_args.args[0]
    assert context["date"] == DAY.isoformat()
    assert context["today"]["data_source"] == "test"
    assert p.trend_analyzer.analyze.call_args.args[0].iloc[-1]["date"] == DAY
    p.db.get_data_range.assert_not_called()
    p.db.get_analysis_context.assert_not_called()
    assert prepared_history.get() is None


def test_batch_prefetch_failure_is_optional(monkeypatch):
    p = pipeline()
    p.fetcher_manager.get_realtime_quotes.side_effect = RuntimeError("prefetch down")
    p.fetcher_manager.get_instrument_info.side_effect = RuntimeError("prefetch down")
    p.process_single_stock = Mock(side_effect=lambda code, **kwargs: success(code))
    codes = [f"TEST{i}.US" for i in range(5)]
    assert len(p.run(codes)) == 5
    assert p.failures == []

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from finance_analysis.tasks.celery.jobs.a_share_pre_close_review.config import PreCloseReviewConfig
from finance_analysis.tasks.celery.jobs.a_share_pre_close_review.data_source import (
    ALLOWED_DATA_SOURCES,
    ASharePreCloseDataSource,
)
from finance_analysis.tasks.celery.jobs.a_share_pre_close_review.llm import ASharePreCloseWebLLM
from finance_analysis.tasks.celery.jobs.a_share_pre_close_review.reporter import render_notification
from finance_analysis.tasks.celery.jobs.a_share_pre_close_review.service import ASharePreCloseReviewService
from finance_analysis.tasks.lifecycle import TaskSkipped

NOW = datetime(2026, 6, 23, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def _limits(**overrides):
    values = {
        "minimum_market_rows": 3,
        "minimum_index_count": 2,
        "minimum_sector_count": 1,
        "history_days": 30,
        "minute_bar_count": 30,
        "minimum_minute_bars": 10,
        "max_strong_sectors": 2,
        "sector_ranking_scan_limit": 4,
        "max_candidates": 2,
        "max_board_lookups": 10,
        "max_news_entities": 4,
        "web_llm_attempts": 1,
    }
    values.update(overrides)
    return PreCloseReviewConfig(**values)


class FakeDataSource:
    def __init__(self, *, snapshot_time: datetime = NOW, quote_time: datetime | None = None):
        self.snapshot_time = snapshot_time
        self.quote_time = quote_time
        self.sources_used = ["efinance", "akshare"]

    def get_market_snapshot_rows(self):
        timestamp = self.snapshot_time.isoformat()
        quote_time = self.quote_time.isoformat() if self.quote_time else None
        return [
            {
                "code": "600001",
                "name": "持仓一",
                "price": 10.5,
                "pre_close": 10.0,
                "open": 10.1,
                "high": 10.6,
                "low": 10.0,
                "change_pct": 5.0,
                "amount": 2_000_000_000,
                "turnover_rate": 4.0,
                "snapshot_time": timestamp,
                "quote_time": quote_time,
            },
            {
                "code": "600002",
                "name": "候选一",
                "price": 20.8,
                "pre_close": 20.0,
                "open": 20.1,
                "high": 21.0,
                "low": 20.0,
                "change_pct": 4.0,
                "amount": 3_000_000_000,
                "turnover_rate": 5.0,
                "snapshot_time": timestamp,
                "quote_time": quote_time,
            },
            {
                "code": "600003",
                "name": "普通股",
                "price": 10.1,
                "pre_close": 10.0,
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "change_pct": 1.0,
                "amount": 1_000_000_000,
                "turnover_rate": 2.0,
                "snapshot_time": timestamp,
                "quote_time": quote_time,
            },
        ]

    def get_main_indices(self):
        return [
            {"code": "sh000001", "name": "上证指数", "current": 3200, "change_pct": 0.8},
            {"code": "sh000300", "name": "沪深300", "current": 3900, "change_pct": 0.9},
        ]

    def get_sector_rankings(self, n):
        return (
            [
                {
                    "name": "电子",
                    "change_pct": 3.2,
                    "price": 103.0,
                    "open": 100.0,
                    "high": 103.2,
                }
            ],
            [],
        )

    def get_daily_history(self, code, *, days):
        closes = [10 + index * 0.1 for index in range(20)]
        return pd.DataFrame({"close": closes, "volume": [1000] * 20}), "efinance"

    def get_minute_bars(self, code, *, count, now=None):
        return [{"close": 10 + index * 0.02} for index in range(20)]

    def get_belonging_boards(self, code):
        return ["电子"]


class FakeWebClient:
    def __init__(self, *, fail=False, action="reduce", include_share_count=False, malformed_final=False):
        self.fail = fail
        self.action = action
        self.include_share_count = include_share_count
        self.malformed_final = malformed_final
        self.requests = []

    def complete_json(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("web llm down")
        if request.call_type == "a_share_pre_close_news":
            payload = json.loads(request.messages[1]["content"].split("输入：", 1)[1])
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "items": [
                            {
                                "entity_key": item["key"],
                                "summary": "近期消息已核对",
                                "impact": "neutral",
                                "coverage": "complete",
                                "sources": [
                                    {
                                        "title": "示例新闻",
                                        "url": "https://example.com/news",
                                        "published_at": "2026-06-23",
                                    }
                                ],
                            }
                            for item in payload["entities"]
                        ]
                    },
                    ensure_ascii=False,
                )
            )
        if self.malformed_final:
            return SimpleNamespace(text="not-json")
        rationale = "建议卖出100股" if self.include_share_count else "相对板块走弱，控制尾盘风险"
        return SimpleNamespace(
            text=json.dumps(
                {
                    "market_summary": {
                        "state": "risk_on",
                        "conclusion": "市场偏强但尾盘仍需确认",
                        "rationale": ["指数与宽度同向"],
                    },
                    "sector_views": [{"name": "电子", "continuity": "trend", "rationale": "趋势延续"}],
                    "risks": ["尾盘板块分歧"],
                    "holdings": [
                        {
                            "code": "600001",
                            "action": self.action,
                            "percent_min": 20,
                            "percent_max": 30,
                            "condition": "跌破分时支撑",
                            "rationale": rationale,
                            "invalidation": "重新站上日内高点",
                        }
                    ],
                    "candidates": [
                        {
                            "code": "600002",
                            "rationale": "板块共振",
                            "condition": "尾盘维持强势",
                            "invalidation": "板块回落",
                        }
                    ],
                    "invalidation_conditions": ["市场宽度快速转弱"],
                    "confidence": "high",
                    "data_note": "行情完整",
                },
                ensure_ascii=False,
            )
        )


class FakeReporter:
    def __init__(self, *, send_result=True):
        self.calendar_calls = 0
        self.notification_calls = 0
        self.send_result = send_result

    def record_to_calendar(self, summary):
        self.calendar_calls += 1
        return 123

    def send_notification(self, summary, *, send_notification):
        if send_notification:
            self.notification_calls += 1
            return self.send_result
        return False


def _holding():
    return SimpleNamespace(
        code="600001",
        name="持仓一",
        quantity=Decimal("1000"),
        avg_cost=Decimal("9.50"),
        market_type="CN",
    )


def _service(*, data=None, client=None, reporter=None, limits=None, recent_results=None):
    limits = limits or _limits()
    client = client or FakeWebClient()
    web_llm = ASharePreCloseWebLLM(SimpleNamespace(), limits, client=client)
    return ASharePreCloseReviewService(
        config=SimpleNamespace(),
        limits=limits,
        data_source=data or FakeDataSource(),
        web_llm=web_llm,
        reporter=reporter or FakeReporter(),
        holdings_provider=lambda: [_holding()],
        recent_results_provider=lambda: recent_results
        or [
            {
                "trading_date": "2026-06-22",
                "breadth": {"total_amount": 5000},
                "strong_sectors": [{"name": "电子"}],
            }
        ],
        existing_news_provider=lambda entities: [],
        use_lock=False,
    )


@pytest.fixture(autouse=True)
def trading_day(monkeypatch):
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.a_share_pre_close_review.service.is_a_share_trading_day",
        lambda check_date=None, current_time=None: True,
    )


def test_trading_day_1430_completes_and_sends_one_notification():
    reporter = FakeReporter()
    summary = _service(reporter=reporter).run(now=NOW)

    assert summary.trading_date.isoformat() == "2026-06-23"
    assert summary.data_quality.fresh_quotes is True
    assert summary.data_quality.sufficient_for_active_advice is True
    assert summary.holdings[0].code == "600001"
    assert summary.decision["holdings"][0]["action"] == "reduce"
    assert summary.decision["holdings"][0]["percent_min"] == 20
    assert summary.notification_sent is True
    assert reporter.notification_calls == 1
    assert reporter.calendar_calls == 1


def test_non_trading_day_skips(monkeypatch):
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.a_share_pre_close_review.service.is_a_share_trading_day",
        lambda check_date=None, current_time=None: False,
    )
    with pytest.raises(TaskSkipped, match="不是 A 股交易日"):
        _service().run(now=NOW)


def test_data_source_is_explicitly_a_share_only_without_longbridge():
    source = inspect.getsource(ASharePreCloseDataSource)

    assert ALLOWED_DATA_SOURCES == ("efinance", "akshare")
    assert "LongbridgeFetcher" not in source
    assert "DataFetcherManager" not in source


def test_stale_quotes_force_low_confidence_and_only_safe_actions():
    stale = FakeDataSource(snapshot_time=NOW, quote_time=NOW - timedelta(minutes=30))
    client = FakeWebClient(action="add_on_condition")
    summary = _service(data=stale, client=client).run(now=NOW)

    assert summary.data_quality.fresh_quotes is False
    assert summary.decision["confidence"] == "low"
    assert {item["action"] for item in summary.decision["holdings"]} <= {"maintain", "watch"}
    assert summary.decision["candidates"] == []


def test_web_llm_only_receives_bounded_final_entities():
    client = FakeWebClient()
    summary = _service(client=client, limits=_limits(max_news_entities=4)).run(now=NOW)

    news_requests = [item for item in client.requests if item.call_type == "a_share_pre_close_news"]
    decision_requests = [item for item in client.requests if item.call_type == "a_share_pre_close_decision"]
    assert len(news_requests) == 1
    assert len(decision_requests) == 1
    assert all(item.provider == "llm_web" for item in client.requests)
    assert news_requests[0].timeout == 180
    payload = json.loads(news_requests[0].messages[1]["content"].split("输入：", 1)[1])
    assert len(payload["entities"]) == 4
    assert summary.llm_calls == 2


def test_each_web_llm_stage_retries_at_most_once():
    client = FakeWebClient(fail=True)
    summary = _service(client=client, limits=_limits(web_llm_attempts=2)).run(now=NOW)

    news_requests = [item for item in client.requests if item.call_type == "a_share_pre_close_news"]
    decision_requests = [item for item in client.requests if item.call_type == "a_share_pre_close_decision"]
    assert len(news_requests) == 2
    assert len(decision_requests) == 2
    assert summary.llm_calls == 4
    assert summary.fallback_used is True


def test_web_llm_stops_retrying_when_task_budget_is_exhausted(monkeypatch):
    client = FakeWebClient(fail=True)
    limits = _limits(web_llm_attempts=2)
    web_llm = ASharePreCloseWebLLM(SimpleNamespace(), limits, client=client)
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.a_share_pre_close_review.llm.time.monotonic",
        iter([0.0, 181.0]).__next__,
    )
    warnings = []

    result = web_llm.research_news(
        [{"key": "market:cn", "type": "market", "name": "A股市场", "code": ""}],
        [],
        trading_date="2026-06-23",
        warnings=warnings,
        deadline=180.0,
    )

    assert result == []
    assert len(client.requests) == 1
    assert client.requests[0].timeout == 180
    assert any("时间预算已耗尽" in item for item in warnings)


def test_web_llm_failure_still_completes_with_fallback():
    reporter = FakeReporter()
    summary = _service(client=FakeWebClient(fail=True), reporter=reporter).run(now=NOW)

    assert summary.fallback_used is True
    assert {item["action"] for item in summary.decision["holdings"]} <= {"maintain", "watch"}
    assert reporter.notification_calls == 1
    assert summary.notification_sent is True


def test_malformed_final_llm_output_uses_validated_fallback():
    summary = _service(client=FakeWebClient(malformed_final=True)).run(now=NOW)

    assert summary.fallback_used is True
    assert {item["action"] for item in summary.decision["holdings"]} <= {"maintain", "watch"}


def test_notification_failure_does_not_fail_review_or_retry_send():
    reporter = FakeReporter(send_result=False)
    summary = _service(reporter=reporter).run(now=NOW)

    assert summary.notification_sent is False
    assert summary.calendar_id == 123
    assert reporter.notification_calls == 1


def test_advice_uses_percentages_and_rejects_specific_share_counts():
    summary = _service(client=FakeWebClient(include_share_count=True)).run(now=NOW)
    advice = summary.decision["holdings"][0]
    notification = render_notification(summary)

    assert (advice["percent_min"], advice["percent_max"]) == (20, 30)
    assert "100股" not in advice["rationale"]
    assert "100股" not in notification
    assert "20%-30%" in notification


def test_duplicate_completed_review_is_skipped():
    with pytest.raises(TaskSkipped, match="已经完成"):
        _service(recent_results=[{"trading_date": "2026-06-23"}]).run(now=NOW)


def test_task_result_is_compact_and_keeps_comparison_fields():
    result = _service().run(now=NOW).to_task_result_dict()

    assert result["trading_date"] == "2026-06-23"
    assert result["strong_sectors"][0]["name"] == "电子"
    assert result["decision"]["holdings"][0]["percent_min"] == 20
    assert len(json.dumps(result, ensure_ascii=False)) < 12_000
    assert "quantity" not in json.dumps(result, ensure_ascii=False)


def test_existing_intraday_task_and_new_task_are_both_registered():
    from finance_analysis.tasks.celery.app import celery_app

    celery_app.loader.import_default_modules()
    assert "scheduled.analysis_a_share_intraday" in celery_app.tasks
    assert "scheduled.analysis_a_share_pre_close_review" in celery_app.tasks

    task = celery_app.tasks["scheduled.analysis_a_share_pre_close_review"]
    assert task.soft_time_limit == 570
    assert task.time_limit == 600

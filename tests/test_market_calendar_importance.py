# -*- coding: utf-8 -*-
"""Tests for market calendar LLM importance scoring."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

from finance_analysis.database.models import FinanceEvent
from finance_analysis.llm.types import LLMResult
from finance_analysis.tasks.celery.jobs.market_calendar_sync.importance import (
    EventCompanyContext,
    MarketCalendarImportanceService,
    PROMPT_VERSION,
    build_event_importance_prompt,
    compute_importance_input_hash,
    normalize_importance_results,
)


def _event(
    *,
    event_id: int = 1,
    symbol: str | None = "NVDA",
    calendar_type: str = "earnings",
    title: str = "NVIDIA earnings",
    star: int | None = 3,
) -> FinanceEvent:
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    return FinanceEvent(
        id=event_id,
        provider="longbridge",
        event_key=f"event-{event_id}",
        calendar_type=calendar_type,
        market="US",
        symbol=symbol,
        counter_name="NVIDIA" if symbol else None,
        event_type="Release",
        activity_type="Earnings",
        event_date=date(2026, 6, 20),
        event_datetime=now,
        title=title,
        content=f"{title} content",
        star=star,
        data_kv_json='[{"key":"EPS","value":"1.23"}]',
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )


class _FakeRepo:
    def __init__(self, events):
        self.events = list(events)
        self.updated = []
        self.list_calls = 0

    def list_events_by_ids(self, event_ids):
        self.list_calls += 1
        by_id = {event.id: event for event in self.events}
        return [by_id[event_id] for event_id in event_ids if event_id in by_id]

    def update_importance_assessment(self, event_id, **kwargs):
        self.updated.append({"event_id": event_id, **kwargs})
        return True


class _FakeQuoteFetcher:
    def __init__(self, quotes=None, exc: Exception | None = None):
        self.quotes = quotes or {}
        self.exc = exc
        self.calls = []

    def get_realtime_quote(self, symbol):
        self.calls.append(symbol)
        if self.exc is not None:
            raise self.exc
        return self.quotes.get(symbol)


class _FakeLightweightContextFetcher:
    def __init__(self):
        self.context_calls = []
        self.realtime_calls = []

    def get_company_quote_context(self, symbol):
        self.context_calls.append(symbol)
        return {"name": "NVIDIA", "total_mv": 1000.0, "price": 10.0}

    def get_realtime_quote(self, symbol):
        self.realtime_calls.append(symbol)
        raise AssertionError("get_realtime_quote should not be used for importance scoring")


class _FakeLLMClient:
    def __init__(self, responses=None, available=True):
        self.responses = list(responses or [])
        self.available = available
        self.requests = []

    def is_available(self):
        return self.available

    def complete_json(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResult(text=response, model_used="test-model", usage={})


def test_prompt_contains_required_context_and_rules():
    prompt = build_event_importance_prompt(
        [
            {
                "event_id": 123,
                "calendar_type": "earnings",
                "symbol": "MU",
                "company_name": "Micron Technology",
                "provider_star": 2,
                "market_cap": 123456.0,
                "title": "MU earnings",
            }
        ]
    )

    assert "event_id" in prompt
    assert "earnings" in prompt
    assert "MU" in prompt
    assert "Micron Technology" in prompt
    assert "provider_star" in prompt
    assert "market_cap" in prompt
    assert "不预测涨跌" in prompt
    assert "普通小公司的常规财报原则上不应超过 5 分" in prompt
    assert "大公司和行业龙头财报通常高分" in prompt
    assert "FOMC、CPI、PCE、非农" in prompt


def test_normalize_importance_results_clamps_and_dedupes():
    results = normalize_importance_results(
        [
            {"event_id": 1, "importance_score": 12, "importance_reason": "  高  分  ", "confidence": 1.2},
            {"event_id": 1, "importance_score": 7, "importance_reason": "duplicate", "confidence": 0.5},
            {"event_id": 2, "importance_score": -1, "importance_reason": "低", "confidence": -0.3},
            {"event_id": 999, "importance_score": 9, "importance_reason": "unknown", "confidence": 0.9},
        ],
        [1, 2],
    )

    assert results == [
        {"event_id": 1, "importance_score": 10, "importance_reason": "高 分", "confidence": 1.0},
        {"event_id": 2, "importance_score": 1, "importance_reason": "低", "confidence": 0.0},
    ]


def test_same_input_hash_skips_llm():
    event = _event()
    context = EventCompanyContext(symbol="NVDA", company_name="NVIDIA", market_cap=1000.0, current_price=10.0)
    event.importance_score = 8
    event.importance_prompt_version = PROMPT_VERSION
    event.importance_input_hash = compute_importance_input_hash(event, context)
    repo = _FakeRepo([event])
    quote_fetcher = _FakeQuoteFetcher({"NVDA": SimpleNamespace(name="NVIDIA", total_mv=1000.0, price=10.0)})
    llm = _FakeLLMClient([])

    result = MarketCalendarImportanceService(repo=repo, quote_fetcher=quote_fetcher, llm_client=llm).score_event_ids([1])

    assert result["skipped"] == 1
    assert llm.requests == []
    assert repo.updated == []


def test_prompt_version_change_rescores_event():
    event = _event()
    event.importance_score = 8
    event.importance_prompt_version = "old"
    event.importance_input_hash = "stale"
    repo = _FakeRepo([event])
    quote_fetcher = _FakeQuoteFetcher({"NVDA": SimpleNamespace(name="NVIDIA", total_mv=1000.0, price=10.0)})
    llm = _FakeLLMClient([json.dumps([{"event_id": 1, "importance_score": 9, "importance_reason": "龙头财报", "confidence": 0.8}])])

    result = MarketCalendarImportanceService(repo=repo, quote_fetcher=quote_fetcher, llm_client=llm).score_event_ids([1])

    assert result["scored"] == 1
    assert repo.updated[0]["prompt_version"] == PROMPT_VERSION
    assert repo.updated[0]["score"] == 9


def test_market_cap_query_is_cached_by_symbol():
    events = [_event(event_id=1, symbol="NVDA"), _event(event_id=2, symbol="NVDA")]
    repo = _FakeRepo(events)
    quote_fetcher = _FakeQuoteFetcher({"NVDA": SimpleNamespace(name="NVIDIA", total_mv=1000.0, price=10.0)})
    llm = _FakeLLMClient(
        [
            json.dumps(
                [
                    {"event_id": 1, "importance_score": 9, "importance_reason": "龙头财报", "confidence": 0.8},
                    {"event_id": 2, "importance_score": 8, "importance_reason": "龙头事件", "confidence": 0.7},
                ]
            )
        ]
    )

    MarketCalendarImportanceService(repo=repo, quote_fetcher=quote_fetcher, llm_client=llm).score_event_ids([1, 2])

    assert quote_fetcher.calls == ["NVDA"]
    assert len(repo.updated) == 2


def test_service_prefers_lightweight_company_context_over_realtime_quote():
    event = _event()
    repo = _FakeRepo([event])
    quote_fetcher = _FakeLightweightContextFetcher()
    llm = _FakeLLMClient([json.dumps([{"event_id": 1, "importance_score": 9, "importance_reason": "龙头财报", "confidence": 0.8}])])

    MarketCalendarImportanceService(repo=repo, quote_fetcher=quote_fetcher, llm_client=llm).score_event_ids([1])

    assert quote_fetcher.context_calls == ["NVDA"]
    assert quote_fetcher.realtime_calls == []
    assert '"market_cap": 1000.0' in llm.requests[0].messages[1]["content"]


def test_market_cap_failure_still_scores_with_null_market_cap():
    event = _event()
    repo = _FakeRepo([event])
    quote_fetcher = _FakeQuoteFetcher(exc=RuntimeError("quote down"))
    llm = _FakeLLMClient([json.dumps([{"event_id": 1, "importance_score": 6, "importance_reason": "信息有限", "confidence": 0.4}])])

    result = MarketCalendarImportanceService(repo=repo, quote_fetcher=quote_fetcher, llm_client=llm).score_event_ids([1])

    assert result["scored"] == 1
    assert '"market_cap": null' in llm.requests[0].messages[1]["content"]


def test_single_batch_failure_does_not_block_other_batches():
    events = [_event(event_id=1, symbol="AAA"), _event(event_id=2, symbol="BBB")]
    repo = _FakeRepo(events)
    quote_fetcher = _FakeQuoteFetcher(
        {
            "AAA": SimpleNamespace(name="AAA", total_mv=100.0, price=1.0),
            "BBB": SimpleNamespace(name="BBB", total_mv=200.0, price=2.0),
        }
    )
    llm = _FakeLLMClient(
        [
            RuntimeError("llm batch down"),
            json.dumps([{"event_id": 2, "importance_score": 7, "importance_reason": "有行业关注", "confidence": 0.6}]),
        ]
    )

    result = MarketCalendarImportanceService(
        repo=repo,
        quote_fetcher=quote_fetcher,
        llm_client=llm,
        batch_size=1,
    ).score_event_ids([1, 2])

    assert result["scored"] == 1
    assert result["errors"]
    assert [item["event_id"] for item in repo.updated] == [2]


def test_llm_unavailable_skips_safely():
    repo = _FakeRepo([_event()])
    llm = _FakeLLMClient(available=False)

    result = MarketCalendarImportanceService(repo=repo, quote_fetcher=_FakeQuoteFetcher(), llm_client=llm).score_event_ids([1])

    assert result["errors"] == ["llm_unavailable"]
    assert repo.list_calls == 0
    assert repo.updated == []


def test_invalid_json_does_not_overwrite_existing_score():
    event = _event()
    event.importance_score = 8
    event.importance_prompt_version = "old"
    repo = _FakeRepo([event])
    quote_fetcher = _FakeQuoteFetcher({"NVDA": SimpleNamespace(name="NVIDIA", total_mv=1000.0, price=10.0)})
    llm = _FakeLLMClient(["not json"])

    result = MarketCalendarImportanceService(repo=repo, quote_fetcher=quote_fetcher, llm_client=llm).score_event_ids([1])

    assert result["scored"] == 0
    assert repo.updated == []
    assert event.importance_score == 8

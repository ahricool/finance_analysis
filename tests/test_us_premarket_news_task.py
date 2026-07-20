# -*- coding: utf-8 -*-
"""Tests for the US premarket news intelligence task."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.providers.longbridge.news import LongbridgeNewsRecord
from finance_analysis.tasks.celery.jobs.us_premarket_news.domain_service import (
    USPremarketNewsService,
    build_premarket_symbol_universe,
    normalize_us_symbol,
    premarket_news_window,
)
from finance_analysis.tasks.celery.jobs.us_premarket_news.llm import (
    normalize_impact_results,
    normalize_importance_results,
)
from finance_analysis.tasks.celery.jobs.us_premarket_news.models import PremarketNewsSummary
from finance_analysis.tasks.celery.jobs.us_premarket_news.notifications import render_calendar_content


def test_normalize_us_symbol_strips_us_suffix_and_preserves_share_class():
    assert normalize_us_symbol(" aapl.us ") == "AAPL"
    assert normalize_us_symbol("$nvda") == "NVDA"
    assert normalize_us_symbol("BRK.B") == "BRK.B"


def test_build_premarket_symbol_universe_merges_watch_list_and_nasdaq_top_20():
    symbols = build_premarket_symbol_universe(["aapl.us", "TSLA", "CUSTOM"])

    assert symbols[0:3] == ["AAPL", "TSLA", "CUSTOM"]
    assert "NVDA" in symbols
    assert "GOOGL" in symbols
    assert symbols.count("AAPL") == 1
    assert len(symbols) == 21


def test_premarket_news_window_uses_yesterday_midnight_beijing_to_run_time():
    now = datetime(2026, 6, 18, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    start_utc, end_utc = premarket_news_window(now)

    assert start_utc == datetime(2026, 6, 16, 16, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)


def test_normalize_importance_results_clamps_values_and_limits_to_top_10():
    raw = [
        {
            "news_id_or_url": f"https://longbridge.com/news/{index}",
            "title": f"Title {index}",
            "related_symbols": ["nvda.us", ""],
            "importance_score": 99 - index,
            "event_type": "unknown",
            "time_sensitivity": "soon",
            "confidence": 2,
        }
        for index in range(12)
    ]

    parsed = normalize_importance_results(raw)

    assert len(parsed) == 10
    assert parsed[0]["importance_score"] == 10
    assert parsed[0]["event_type"] == "other"
    assert parsed[0]["time_sensitivity"] == "this_week"
    assert parsed[0]["confidence"] == 1
    assert parsed[0]["related_symbols"] == ["NVDA"]


def test_normalize_impact_results_clamps_score_and_unknown_impact():
    parsed = normalize_impact_results(
        [
            {
                "news_id_or_url": "https://longbridge.com/news/1",
                "title": "News",
                "related_symbols": ["amd.us"],
                "impact": "certainly_up",
                "impact_score": 99,
                "confidence": -1,
                "watch_points": ["watch demand"],
                "risk_notes": ["valuation risk"],
            }
        ]
    )

    assert parsed == [
        {
            "news_id_or_url": "https://longbridge.com/news/1",
            "title": "News",
            "related_symbols": ["AMD"],
            "impact": "unclear",
            "impact_score": 5,
            "confidence": 0,
            "reason": "",
            "watch_points": ["watch demand"],
            "risk_notes": ["valuation risk"],
        }
    ]


def test_render_calendar_content_includes_counts_and_impact_details():
    started_at = datetime(2026, 6, 18, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    summary = PremarketNewsSummary(
        started_at=started_at,
        finished_at=started_at,
        symbols=["NVDA"],
        fetched_news_count=2,
        inserted_news_count=1,
        candidates_count=2,
        important_news=[
            {
                "news_id_or_url": "https://longbridge.com/news/1",
                "title": "NVIDIA raises guidance",
                "related_symbols": ["NVDA"],
                "importance_score": 9,
                "importance_reason": "Directly changes guidance.",
                "event_type": "guidance",
            }
        ],
        impact_results=[
            {
                "news_id_or_url": "https://longbridge.com/news/1",
                "impact": "bullish",
                "impact_score": 4,
                "confidence": 0.8,
                "reason": "Short-term sentiment positive; fundamentals depend on execution.",
            }
        ],
    )

    content = render_calendar_content(summary)

    assert "symbols 数量：1" in content
    assert "抓取新闻数量：2" in content
    assert "新增入库数量：1" in content
    assert "impact_score" in content
    assert "Short-term sentiment positive" in content


def test_service_run_continues_when_single_symbol_fetch_fails():
    service = USPremarketNewsService(
        config=MagicMock(),
        longbridge_fetcher=MagicMock(),
        news_fetcher=MagicMock(),
        llm_analyzer=MagicMock(),
        reporter=MagicMock(),
        db=MagicMock(),
    )
    service._count_premarket_news_rows = MagicMock(side_effect=[10, 11])
    service._load_candidate_news = MagicMock(return_value=[])
    service.llm_analyzer.select_important_news.return_value = []
    service.llm_analyzer.judge_impact.return_value = []
    service.reporter.record_to_calendar.return_value = 123
    service.reporter.send_notification.return_value = True

    def _fake_fetch(symbol, *, query_id):
        del query_id
        if symbol == "BROKEN":
            raise RuntimeError("temporary outage")
        if symbol == "NVDA":
            return [
                LongbridgeNewsRecord(
                    news_id="1",
                    title="NVIDIA news",
                    description="Summary",
                    url="https://longbridge.com/news/1",
                    published_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
                )
            ]
        return []

    service._fetch_symbol_news = MagicMock(side_effect=_fake_fetch)

    summary = service.run(["BROKEN", "NVDA"], now=datetime(2026, 6, 18, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

    assert summary.fetched_news_count == 1
    assert summary.inserted_news_count == 1
    assert any("BROKEN" in warning for warning in summary.warnings)
    assert summary.calendar_id == 123
    assert summary.notification_sent is True


def test_stock_name_lookup_does_not_open_quote_context():
    quote_fetcher = MagicMock()
    service = USPremarketNewsService(
        config=MagicMock(),
        longbridge_fetcher=quote_fetcher,
        news_fetcher=MagicMock(),
        llm_analyzer=MagicMock(),
        reporter=MagicMock(),
        db=MagicMock(),
    )

    assert service._get_stock_name("COIN") == "Coinbase"
    assert service._get_stock_name("UNKNOWN") == ""
    quote_fetcher.get_stock_name.assert_not_called()

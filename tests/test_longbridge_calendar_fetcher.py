# -*- coding: utf-8 -*-
"""Tests for Longbridge finance calendar fetcher."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from finance_analysis.integrations.market_data.providers.longbridge.calendar import LongbridgeCalendarFetcher


def test_fetch_calendar_calls_single_sdk_finance_calendar_method():
    fetcher = LongbridgeCalendarFetcher()
    ctx = MagicMock()
    ctx.finance_calendar.return_value = SimpleNamespace(list=[])
    fetcher._get_ctx = MagicMock(return_value=ctx)
    fetcher._resolve_category = MagicMock(return_value="REPORT")
    fetcher._resolve_market = MagicMock(return_value="US")

    result = fetcher.fetch_earnings_calendar(date(2026, 6, 18), date(2026, 7, 18), "US")

    assert result == []
    ctx.finance_calendar.assert_called_once_with("REPORT", "2026-06-18", "2026-07-18", "US")


def test_fetch_calendar_passes_sdk_expected_request_types_with_market_enum():
    from longbridge.openapi import CalendarCategory, Market

    fetcher = LongbridgeCalendarFetcher()
    ctx = MagicMock()
    ctx.finance_calendar.return_value = SimpleNamespace(list=[])
    fetcher._get_ctx = MagicMock(return_value=ctx)

    result = fetcher.fetch_earnings_calendar(date(2026, 6, 18), date(2026, 7, 18), Market.US)

    assert result == []
    ctx.finance_calendar.assert_called_once_with(
        CalendarCategory.Report,
        "2026-06-18",
        "2026-07-18",
        "US",
    )


def test_normalize_response_flattens_date_groups_and_builds_markdown():
    fetcher = LongbridgeCalendarFetcher()
    info = SimpleNamespace(
        id="event-1",
        symbol="NVDA.US",
        market="US",
        counter_name="NVIDIA",
        event_type="Release",
        activity_type="Earnings",
        date=date(2026, 6, 20),
        datetime=None,
        date_type="confirmed",
        financial_market_time="after_close",
        content="Q2 earnings",
        star=3,
        currency="USD",
        data_kv=[SimpleNamespace(key="EPS", value="1.23", value_raw="1.23", value_type="string")],
    )
    response = SimpleNamespace(list=[SimpleNamespace(date=date(2026, 6, 20), infos=[info])])

    events = fetcher.normalize_response(response, calendar_type="earnings", market="US")

    assert len(events) == 1
    event = events[0]
    assert event["provider"] == "longbridge"
    assert event["calendar_type"] == "earnings"
    assert event["provider_event_id"] == "event-1"
    assert event["symbol"] == "NVDA"
    assert event["event_date"] == "2026-06-20"
    assert event["star"] == 3
    assert event["title"].startswith("NVDA NVIDIA 财报")
    assert len(event["title"]) <= 120
    assert "类型：财报" in event["content_markdown"]
    assert "EPS" in event["content_markdown"]

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

    assert result.events == []
    ctx.finance_calendar.assert_called_once_with("REPORT", "2026-06-18", "2026-07-18", "US")


def test_fetch_calendar_passes_sdk_expected_request_types_with_market_enum():
    from longbridge.openapi import CalendarCategory, Market

    fetcher = LongbridgeCalendarFetcher()
    ctx = MagicMock()
    ctx.finance_calendar.return_value = SimpleNamespace(list=[])
    fetcher._get_ctx = MagicMock(return_value=ctx)

    result = fetcher.fetch_earnings_calendar(date(2026, 6, 18), date(2026, 7, 18), Market.US)

    assert result.events == []
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

    result = fetcher.normalize_response(response, calendar_type="earnings", market="US")

    events = result.events
    assert len(events) == 1
    event = events[0]
    assert event["provider"] == "longbridge"
    assert event["calendar_type"] == "earnings"
    assert event["provider_event_id"] == "event-1"
    assert event["symbol"] == "NVDA.US"
    assert event["event_date"] == "2026-06-20"
    assert event["market_session"] == "amc"
    assert "star" not in event
    assert event["title"].startswith("NVDA.US NVIDIA 财报")
    assert len(event["title"]) <= 120
    assert "EPS" in event["content"]


def test_actual_sdk_dotted_date_unix_time_and_chinese_session():
    result = LongbridgeCalendarFetcher().normalize_response(
        {
            "list": [
                {
                    "date": "2026-06-18",
                    "infos": [
                        dict(
                            symbol="NVDA.US",
                            market="US",
                            date="2026.06.18",
                            datetime="1781812800",
                            date_type="盘后",
                            content="Q2 earnings",
                            financial_market_time="",
                        )
                    ],
                }
            ]
        },
        calendar_type="earnings",
        market="US",
    )
    assert len(result.events) == 1
    assert result.events[0]["event_date"] == "2026-06-18"
    assert result.events[0]["event_datetime"].endswith("+00:00")
    assert result.events[0]["market_session"] == "amc"


def test_cursor_pagination_retains_previous_page_when_next_fails():
    fetcher = LongbridgeCalendarFetcher()
    ctx = MagicMock()
    ctx.finance_calendar.side_effect = [
        {
            "list": [{"date": "2026-06-18", "infos": [dict(symbol="NVDA.US", market="US", content="earnings")]}],
            "next_date": "2026-06-19",
        },
        RuntimeError("second page down"),
    ]
    fetcher._get_ctx = lambda: ctx
    result = fetcher.fetch_earnings_calendar(date(2026, 6, 18), date(2026, 6, 20), "US", ["NVDA.US"])
    assert result.pages_succeeded == 1 and len(result.events) == 1 and result.errors
    assert ctx.finance_calendar.call_args.args[1] == "2026-06-19"


def test_macro_country_is_required_and_bad_row_does_not_stop_others():
    result = LongbridgeCalendarFetcher().normalize_response(
        {
            "list": [
                {
                    "date": "2026-06-18",
                    "infos": [
                        dict(content="CPI", market=None),
                        dict(content="CPI", market="CN"),
                        dict(content="CPI", market="US"),
                    ],
                }
            ]
        },
        calendar_type="macro",
        market="US",
    )
    assert len(result.events) == 1 and result.skipped == 2

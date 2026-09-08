# -*- coding: utf-8 -*-
"""Tests for Longbridge finance calendar fetcher."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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


def test_cn_requests_exchanges_and_normalizes_logical_market_with_universe_filter():
    from longbridge.openapi import CalendarCategory

    fetcher = LongbridgeCalendarFetcher()
    ctx = MagicMock()

    def response(category, start, end, market):
        assert category == CalendarCategory.Report
        assert market in {"SH", "SZ"}
        symbols = ["600519", "600000"] if market == "SH" else ["000001.SZ", "000002.SZ"]
        return {
            "list": [
                {
                    "date": "2026-06-18",
                    "infos": [{"symbol": symbol, "market": market, "content": "财报"} for symbol in symbols],
                }
            ]
        }

    ctx.finance_calendar.side_effect = response
    fetcher._get_ctx = lambda: ctx
    result = fetcher.fetch_earnings_calendar(date(2026, 6, 18), date(2026, 6, 20), "CN", ["600519.SH", "000001.SZ"])
    assert [call.args[3] for call in ctx.finance_calendar.call_args_list] == ["SH", "SZ"]
    assert {event["symbol"] for event in result.events} == {"600519.SH", "000001.SZ"}
    assert all(event["market"] == "CN" for event in result.events)
    assert result.fetched == 4 and result.skipped == 2


@pytest.mark.parametrize("failed_market", ["SH", "SZ"])
def test_cn_exchange_failure_preserves_other_exchange(failed_market):
    fetcher = LongbridgeCalendarFetcher()
    ctx = MagicMock()

    def response(category, start, end, market):
        if market == failed_market:
            raise RuntimeError("exchange unavailable")
        symbol = "600519.SH" if market == "SH" else "000001.SZ"
        return {"list": [{"date": "2026-06-18", "infos": [{"symbol": symbol, "market": market}]}]}

    ctx.finance_calendar.side_effect = response
    fetcher._get_ctx = lambda: ctx
    result = fetcher.fetch_earnings_calendar(date(2026, 6, 18), date(2026, 6, 20), "CN", ["600519.SH", "000001.SZ"])
    assert ctx.finance_calendar.call_count == 2
    assert len(result.events) == 1 and result.events[0]["market"] == "CN"
    assert result.pages_succeeded == 1
    assert len(result.errors) == 1 and f"market={failed_market}" in result.errors[0]


def test_cn_both_exchanges_empty_is_normal():
    fetcher = LongbridgeCalendarFetcher()
    ctx = MagicMock()
    ctx.finance_calendar.return_value = {"list": []}
    fetcher._get_ctx = lambda: ctx
    result = fetcher.fetch_earnings_calendar(date(2026, 6, 18), date(2026, 6, 20), "CN", ["600519.SH"])
    assert not result.events and not result.errors and result.pages_succeeded == 2
    assert [call.args[3] for call in ctx.finance_calendar.call_args_list] == ["SH", "SZ"]


def test_live_sample_eps_types_enrich_yahoo_and_preserve_all_raw_kv():
    import json
    from pathlib import Path
    from finance_analysis.market_calendar.events import merge_events, with_source

    sample = json.loads((Path(__file__).parent / "fixtures/market_calendar/longbridge_report_sample.json").read_text())
    fetcher = LongbridgeCalendarFetcher()
    info = sample["events"][0]
    lb = fetcher.normalize_info(info, calendar_type="earnings", market="US", group_date=date(2026, 9, 3))
    assert lb["eps_estimate"] == 0.01243 and lb["reported_eps"] == 0.03
    assert "eps_surprise_pct" not in lb  # No confirmed provider field; do not invent a mapping.
    assert lb["raw_payload_json"]["longbridge"]["raw"]["details"] == info["data_kv"]
    assert not any("revenue" in key for key in lb)
    yahoo = with_source(
        {
            "provider": "yfinance",
            "calendar_type": "earnings",
            "market": "US",
            "symbol": "IOT.US",
            "event_date": "2026-09-03",
            "eps_estimate": None,
            "reported_eps": None,
        }
    )
    merged = merge_events([yahoo, lb], as_of=date(2026, 9, 3))[0]
    assert merged["provider"] == "yfinance" and merged["eps_estimate"] == 0.01243 and merged["reported_eps"] == 0.03
    pending = fetcher.normalize_info(
        sample["events"][1], calendar_type="earnings", market="US", group_date=date(2026, 9, 8)
    )
    assert pending["eps_estimate"] == -0.056 and "reported_eps" not in pending


@pytest.mark.parametrize("raw", ["0", "NaN", "Infinity", "--", None])
def test_confirmed_eps_type_numeric_validation(raw):
    fetcher = LongbridgeCalendarFetcher()
    result = fetcher.normalize_info(
        {"symbol": "IOT.US", "data_kv": [{"key": "", "value": "--", "value_raw": raw, "value_type": "actual_eps"}]},
        calendar_type="earnings",
        market="US",
        group_date=date(2026, 9, 3),
    )
    if raw == "0":
        assert result["reported_eps"] == 0
    else:
        assert "reported_eps" not in result

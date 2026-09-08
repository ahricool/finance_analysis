"""Yahoo's actual public DataFrame schema; no Ticker requests or network."""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from finance_analysis.integrations.market_data.providers.yfinance_calendar import YFinanceCalendarFetcher

START, END = date(2026, 6, 18), date(2026, 6, 18)


def earnings(symbols):
    return pd.DataFrame(
        [
            dict(
                Symbol=symbol,
                Company=symbol,
                **{
                    "Event Name": "Q2 2026 Earnings Announcement",
                    "Event Start Date": (
                        "2026-06-18T08:00:00Z" if symbol.endswith((".SS", ".SZ")) else "2026-06-18T20:00:00Z"
                    ),
                    "Timing": "AMC",
                    "EPS Estimate": 0,
                    "Reported EPS": float("nan"),
                    "Surprise(%)": float("nan"),
                },
            )
            for symbol in symbols
        ]
    ).set_index("Symbol")


def adapter(pages, kind="earnings"):
    calendar = MagicMock()
    getattr(calendar, f"get_{kind}_calendar").side_effect = pages
    factory = MagicMock(return_value=calendar)
    return YFinanceCalendarFetcher(factory), calendar, factory


def test_full_pagination_before_universe_filter_and_cn_shared_batch():
    fetcher, calendar, factory = adapter(
        [earnings([f"NO{i}" for i in range(100)]), earnings(["NVDA", "600519.SS", "000001.SZ", "BRK-B"])]
    )
    us = fetcher.fetch_earnings_calendar(START, END, "US", ["NVDA.US", "BRK.B.US"])
    cn = fetcher.fetch_earnings_calendar(START, END, "CN", ["600519.SH", "000001.SZ"])
    assert {item["symbol"] for item in us.events} == {"NVDA.US", "BRK.B.US"}
    assert {item["symbol"] for item in cn.events} == {"600519.SH", "000001.SZ"}
    assert us.events[0]["market_session"] == "amc"
    assert us.events[0]["reporting_period"] == "2026-Q2"
    assert us.events[0]["eps_estimate"] == 0 and us.events[0]["reported_eps"] is None
    calls = calendar.get_earnings_calendar.call_args_list
    assert [call.kwargs["offset"] for call in calls] == [0, 100]
    assert all(call.kwargs["filter_most_active"] is False and call.kwargs["limit"] == 100 for call in calls)
    assert factory.call_count == 1
    factory.assert_called_once_with(start=START, end=date(2026, 6, 19))


def test_later_page_failure_keeps_earlier_rows_and_next_shard_continues():
    fetcher, calendar, factory = adapter([earnings(["NVDA"] * 100), RuntimeError("page failed"), pd.DataFrame()])
    result = fetcher.fetch_earnings_calendar(START, date(2026, 6, 25), "US", ["NVDA.US"])
    assert len(result.events) == 100
    assert result.errors and "offset=100" in result.errors[0]
    assert factory.call_count == 2 and result.pages_succeeded == 2


def test_repeated_page_guard_reports_error_instead_of_looping():
    frame = earnings(["NVDA"] * 100)
    fetcher, _, _ = adapter([frame, frame])
    result = fetcher.fetch_earnings_calendar(START, END, "US", ["NVDA.US"])
    assert "repeated" in result.errors[0]


def test_macro_only_explicit_us_with_actual_schema_and_pagination():
    def frame(rows):
        return pd.DataFrame(rows).set_index("Event")

    global_rows = [dict(Event=f"CPI {i}", Region="CN", **{"Event Time": "2026-06-18T12:30:00Z"}) for i in range(100)]
    second = [
        dict(
            Event="CPI YY", Region="US", For="May", Actual=2.4, Expected=2.3, **{"Event Time": "2026-06-18T12:30:00Z"}
        ),
        dict(Event="Unidentified", Region=None, **{"Event Time": "2026-06-18T12:30:00Z"}),
    ]
    fetcher, calendar, _ = adapter([frame(global_rows), frame(second)], "economic_events")
    result = fetcher.fetch_macro_calendar(START, END)
    assert len(result.events) == 1 and result.skipped == 101
    assert result.events[0]["event_type"] == "cpi_yoy"
    assert result.events[0]["reporting_period"] is None  # Month without year is not invented.
    assert "Actual: 2.4" in result.events[0]["content"]
    assert calendar.get_economic_events_calendar.call_args.kwargs["offset"] == 100


def test_row_failure_and_missing_cn_coverage_are_best_effort():
    frame = earnings(["NVDA", "600519.SS"])
    frame.loc["600519.SS", "Event Start Date"] = "invalid"
    fetcher, _, _ = adapter([frame])
    result = fetcher.fetch_earnings_calendar(START, END, "CN", ["600519.SH"])
    assert not result.events and result.errors and result.pages_succeeded == 1


def test_unknown_schema_is_reported_not_silent_empty_success():
    fetcher, _, _ = adapter([pd.DataFrame([{"unexpected": 1}])])
    result = fetcher.fetch_earnings_calendar(START, END, "US", ["NVDA.US"])
    assert result.pages_succeeded == 0 and result.errors

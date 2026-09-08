"""Batch Yahoo Calendars adapter (yfinance >= 1.5.2 public DataFrame schema)."""

from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.calendar import CalendarFetchResult
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider
from finance_analysis.market_calendar.events import macro_type, normalize_session, with_source

logger = logging.getLogger(__name__)


def _inclusive_calendar(start: date, end: date):
    import yfinance as yf

    class InclusiveCalendars(yf.Calendars):
        def _parse_date_param(self, value):
            # yfinance 1.5.2 truncates even datetime inputs to midnight while
            # building inclusive GTE/LTE queries. Keep the final day's time.
            if isinstance(value, datetime):
                return value.isoformat()
            return super()._parse_date_param(value)

    return InclusiveCalendars(start=datetime.combine(start, time.min), end=datetime.combine(end, time.max))


def _value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _time(value: Any, market: str) -> tuple[str, str | None]:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("missing event date")
    tz = ZoneInfo("America/New_York" if market == "US" else "Asia/Shanghai")
    # Yahoo calendar midnight values carry a date, not a reliable release time.
    if timestamp.hour == timestamp.minute == timestamp.second == 0:
        return timestamp.date().isoformat(), None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(tz)
    return timestamp.tz_convert(tz).date().isoformat(), timestamp.tz_convert(timezone.utc).isoformat()


class YFinanceCalendarFetcher:
    def __init__(self, calendar_factory=None):
        self.calendar_factory = calendar_factory
        self._cache = {}

    def _pages(self, calendar_type: str, start: date, end: date) -> tuple[list[dict], CalendarFetchResult]:
        key = (calendar_type, start, end)
        if key in self._cache:
            return self._cache[key]
        factory = self.calendar_factory or _inclusive_calendar
        rows = []
        result = CalendarFetchResult()
        cursor = start
        while cursor <= end:
            stop = min(cursor + timedelta(days=6), end)
            offset = 0
            seen_pages = set()
            try:
                calendar = factory(start=cursor, end=stop)
                method = getattr(
                    calendar, "get_earnings_calendar" if calendar_type == "earnings" else "get_economic_events_calendar"
                )
                while True:
                    kwargs = {"limit": 100, "offset": offset, "force": True}
                    if calendar_type == "earnings":
                        kwargs["filter_most_active"] = False
                    frame = method(**kwargs)
                    if frame is None:
                        raise ValueError("calendar returned None")
                    if frame.empty:
                        result.pages_succeeded += 1
                        break
                    required = {"Event Start Date"} if calendar_type == "earnings" else {"Event Time", "Region"}
                    if not required.issubset(frame.columns):
                        raise ValueError(f"unexpected {calendar_type} columns: {list(frame.columns)}")
                    records = frame.reset_index().to_dict("records")
                    signature = repr(records)
                    if signature in seen_pages:
                        raise ValueError("pagination repeated a page")
                    seen_pages.add(signature)
                    result.pages_succeeded += 1
                    result.fetched += len(records)
                    rows.extend(records)
                    if len(frame) < 100:
                        break
                    offset += len(frame)
            except Exception as exc:
                error = f"{calendar_type} shard={cursor}/{stop} offset={offset}: {exc}"
                result.errors.append(error)
                logger.warning("Yahoo calendar page failed: %s", error)
            cursor = stop + timedelta(days=1)
        self._cache[key] = (rows, result)
        return rows, result

    def fetch_earnings_calendar(self, start, end, market, symbols=()) -> CalendarFetchResult:
        if market == "CN":
            reason = "Yahoo batch earnings calendar has no reliable CN contract; best-effort skipped"
            logger.info(reason)
            return CalendarFetchResult(unsupported_reason=reason)
        if market != "US":
            raise ValueError("only US earnings are supported by the Yahoo calendar adapter")
        # Exact reverse mapping also handles US share classes (BRK.B.US -> BRK-B).
        mapping = {}
        mapping_errors = []
        for symbol in symbols:
            try:
                mapping[YFinanceProvider.to_yfinance_symbol(symbol)] = symbol
            except Exception as exc:
                mapping_errors.append(f"symbol={symbol}: {exc}")
        return self._fetch("earnings", start, end, market, mapping, mapping_errors)

    def fetch_macro_calendar(self, start, end, market="US", symbols=()) -> CalendarFetchResult:
        if market != "US":
            raise ValueError("only US macro is supported")
        return self._fetch("macro", start, end, market, {}, [])

    def _fetch(self, calendar_type, start, end, market, mapping, errors):
        rows, page_result = self._pages(calendar_type, start, end)
        result = CalendarFetchResult(
            errors=[*page_result.errors, *errors],
            pages_succeeded=page_result.pages_succeeded,
            fetched=page_result.fetched,
        )
        for row in rows:
            try:
                raw = {key: _value(value) for key, value in row.items()}
                if calendar_type == "earnings":
                    symbol = mapping.get(str(raw.get("Symbol") or "").upper())
                    if not symbol:
                        result.skipped += 1
                        continue
                    event_date, event_datetime = _time(raw.get("Event Start Date"), market)
                    name = raw.get("Company")
                    period = re.search(r"\bQ([1-4])\s+(20\d{2})\b", str(raw.get("Event Name") or ""), re.I)
                    event = {
                        "reporting_period": f"{period[2]}-Q{period[1]}" if period else None,
                        "symbol": symbol,
                        "counter_name": name,
                        "event_type": "earnings_release",
                        "market_session": normalize_session(raw.get("Timing")),
                        "title": f"{symbol} {name or ''} 财报"[:120],
                        "content": str(raw.get("Event Name") or "财报发布"),
                        "eps_estimate": _number(raw.get("EPS Estimate")),
                        "reported_eps": _number(raw.get("Reported EPS")),
                        "eps_surprise_pct": _number(raw.get("Surprise(%)")),
                    }
                else:
                    if str(raw.get("Region") or "").strip().upper() not in {"US", "USA", "UNITED STATES"}:
                        result.skipped += 1
                        logger.debug("Skip non-US or unidentified Yahoo macro: %s", raw.get("Region"))
                        continue
                    event_date, event_datetime = _time(raw.get("Event Time"), market)
                    name = str(raw.get("Event") or "").strip()
                    if not name:
                        raise ValueError("missing economic event name")
                    measures = {
                        key: raw.get(key)
                        for key in ("Actual", "Expected", "Last", "Revised")
                        if raw.get(key) is not None
                    }
                    event = {
                        "symbol": None,
                        "event_type": macro_type(name),
                        "title": name[:120],
                        "reporting_period": (
                            str(raw["For"]) if re.search(r"\b20\d{2}\b", str(raw.get("For") or "")) else None
                        ),
                        "content": "\n".join([name, *(f"{key}: {value}" for key, value in measures.items())]),
                    }
                if not start <= date.fromisoformat(event_date) <= end:
                    result.skipped += 1
                    continue
                event.update(
                    provider="yfinance",
                    calendar_type=calendar_type,
                    market=market,
                    event_date=event_date,
                    event_datetime=event_datetime,
                )
                result.events.append(with_source(event, raw, observed_at=utc_now()))
            except Exception as exc:
                result.skipped += 1
                result.errors.append(f"row={row.get('Symbol', row.get('Event'))}: {exc}")
                logger.warning("Skip invalid Yahoo calendar row: %s", exc)
        return result

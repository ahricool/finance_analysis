# -*- coding: utf-8 -*-
"""Longbridge finance calendar fetcher."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from finance_analysis.core.time import coerce_aware_utc, utc_now
from finance_analysis.integrations.market_data.providers.longbridge.market import (
    _longbridge_config_kwargs,
    _sanitize_longbridge_env,
)

logger = logging.getLogger(__name__)

PROVIDER = "longbridge"
MARKET_CALENDAR_TIMEZONE = "Asia/Shanghai"
from finance_analysis.integrations.market_data.calendar import CalendarFetchResult
from finance_analysis.integrations.market_data.normalizer import canonical_symbol
from finance_analysis.market_calendar.events import macro_type, normalize_session, with_source


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _none_if_blank(value: Any) -> Optional[str]:
    text = _clean_text(value)
    return text or None


def _enum_name(value: Any) -> str:
    if value is None:
        return ""
    name = getattr(value, "name", None)
    if name:
        return str(name)
    text = str(value)
    if "." in text:
        return text.rsplit(".", 1)[-1]
    return text


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(v) for v in value]
    attrs = {}
    for name in dir(value):
        if name.startswith("_"):
            continue
        try:
            attr = getattr(value, name)
        except Exception:
            continue
        if callable(attr):
            continue
        attrs[name] = _jsonable(attr)
    if attrs:
        return attrs
    return str(value)


def _parse_date(value: Any, fallback: Optional[date] = None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean_text(value).replace(".", "-")
    if text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").date()
            except ValueError:
                pass
    if fallback is not None:
        return fallback
    raise ValueError(f"invalid calendar event date: {value!r}")


def _format_request_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = _parse_date(value)
    return parsed.isoformat()


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return coerce_aware_utc(value)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    text = _clean_text(value)
    if not text:
        return None
    if text.isdigit():
        timestamp = int(text)
        if timestamp == 0:
            return None
        return datetime.fromtimestamp(timestamp / 1000 if timestamp > 10**12 else timestamp, timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(MARKET_CALENDAR_TIMEZONE))
    return parsed.astimezone(timezone.utc)


class LongbridgeCalendarFetcher:
    """Secondary source, requested independently of Yahoo's outcome."""

    _CATEGORY_BY_TYPE = {"earnings": "Report", "macro": "MacroData"}

    def __init__(self) -> None:
        self._ctx = None
        self._config = None

    def _has_credentials(self) -> bool:
        try:
            from finance_analysis.integrations.market_data.config import get_data_provider_config

            config = get_data_provider_config()
            return bool(config.longbridge_app_key and config.longbridge_app_secret and config.longbridge_access_token)
        except Exception:
            return bool(
                os.getenv("LONGBRIDGE_APP_KEY")
                and os.getenv("LONGBRIDGE_APP_SECRET")
                and os.getenv("LONGBRIDGE_ACCESS_TOKEN")
            )

    def _get_ctx(self) -> Any:
        if self._ctx is not None:
            return self._ctx
        if not self._has_credentials():
            raise RuntimeError("Longbridge credentials are not configured")

        from longbridge.openapi import CalendarContext, Config

        _sanitize_longbridge_env()

        try:
            from finance_analysis.integrations.market_data.config import get_data_provider_config

            app_config = get_data_provider_config()
            app_key = app_config.longbridge_app_key
            app_secret = app_config.longbridge_app_secret
            access_token = app_config.longbridge_access_token
        except Exception:
            app_key = os.getenv("LONGBRIDGE_APP_KEY")
            app_secret = os.getenv("LONGBRIDGE_APP_SECRET")
            access_token = os.getenv("LONGBRIDGE_ACCESS_TOKEN")

        for key, value in {
            "LONGBRIDGE_APP_KEY": app_key,
            "LONGBRIDGE_APP_SECRET": app_secret,
            "LONGBRIDGE_ACCESS_TOKEN": access_token,
        }.items():
            if value and not os.environ.get(key):
                os.environ[key] = value

        lb_config = None
        for factory_name in ("from_apikey_env", "from_env"):
            factory = getattr(Config, factory_name, None)
            if factory is None:
                continue
            try:
                lb_config = factory()
                logger.info("[LongbridgeCalendar] Config.%s() success", factory_name)
                break
            except Exception as exc:
                logger.debug("[LongbridgeCalendar] Config.%s() failed: %s", factory_name, exc)

        if lb_config is None:
            lb_config = Config.from_apikey(app_key, app_secret, access_token, **_longbridge_config_kwargs())

        self._config = lb_config
        self._ctx = CalendarContext(lb_config)
        return self._ctx

    def _resolve_category(self, calendar_type: str) -> Any:
        from longbridge.openapi import CalendarCategory

        category_name = self._CATEGORY_BY_TYPE[calendar_type]
        return getattr(CalendarCategory, category_name)

    def _resolve_market(self, market: Any) -> Optional[str]:
        text = _enum_name(market).upper()
        if not text or text == "UNKNOWN":
            return None
        if text.endswith(".US"):
            return "US"
        return text

    def fetch_earnings_calendar(self, start, end, market, symbols=()) -> CalendarFetchResult:
        return self.fetch_calendar("earnings", start, end, market, symbols)

    def fetch_macro_calendar(self, start, end, market="US", symbols=()) -> CalendarFetchResult:
        return self.fetch_calendar("macro", start, end, market, symbols)

    def fetch_calendar(self, calendar_type, start, end, market, symbols=()) -> CalendarFetchResult:
        if calendar_type not in self._CATEGORY_BY_TYPE:
            raise ValueError(f"Unsupported calendar type: {calendar_type}")
        resolved_market = self._resolve_market(market)
        if calendar_type == "macro" and resolved_market != "US":
            raise ValueError("only US macro is supported")
        result = CalendarFetchResult()
        cursor = start
        while cursor <= end:
            try:
                response = self._get_ctx().finance_calendar(
                    self._resolve_category(calendar_type),
                    _format_request_date(cursor),
                    _format_request_date(end),
                    resolved_market,
                )
                page = self.normalize_response(response, calendar_type=calendar_type, market=resolved_market)
                result.events.extend(page.events)
                result.errors.extend(page.errors)
                result.fetched += page.fetched
                result.pages_succeeded += page.pages_succeeded
                next_date = (
                    response.get("next_date") if isinstance(response, Mapping) else getattr(response, "next_date", None)
                )
                if not next_date:
                    break
                next_cursor = _parse_date(next_date)
                if next_cursor <= cursor:
                    raise ValueError(f"non-advancing pagination cursor {next_date}")
                cursor = next_cursor
            except Exception as exc:
                result.errors.append(f"{calendar_type} start={cursor}: {exc}")
                logger.warning("Longbridge calendar page failed: %s", result.errors[-1])
                break
        allowed = set(symbols)
        result.events = [
            event
            for event in result.events
            if start <= _parse_date(event["event_date"]) <= end
            and (calendar_type == "macro" or event["symbol"] in allowed)
        ]
        result.skipped = result.fetched - len(result.events)
        return result

    def normalize_response(self, response, *, calendar_type, market) -> CalendarFetchResult:
        groups = response.get("list") if isinstance(response, Mapping) else getattr(response, "list", response)
        result = CalendarFetchResult(pages_succeeded=1)
        for group in groups or []:
            getter = group.get if isinstance(group, Mapping) else lambda key: getattr(group, key, None)
            for info in getter("infos") or []:
                result.fetched += 1
                try:
                    event = self.normalize_info(
                        info, calendar_type=calendar_type, market=market, group_date=_parse_date(getter("date"))
                    )
                    if event is not None:
                        result.events.append(event)
                except Exception as exc:
                    result.errors.append(f"invalid row: {exc}")
                    logger.warning("Skip invalid Longbridge calendar row: %s", exc)
        result.skipped = result.fetched - len(result.events)
        return result

    def normalize_info(self, info, *, calendar_type, market, group_date) -> Optional[dict]:
        getter = info.get if isinstance(info, Mapping) else lambda key, default=None: getattr(info, key, default)
        explicit_market = _enum_name(getter("market")).upper()
        if calendar_type == "macro" and explicit_market != "US":
            logger.debug("Skip unidentified/non-US Longbridge macro: market=%s", explicit_market)
            return None
        symbol = None
        if calendar_type == "earnings":
            raw_symbol = str(getter("symbol") or "").upper()
            if not raw_symbol:
                return None
            symbol = canonical_symbol(raw_symbol if "." in raw_symbol else f"{raw_symbol}.{market}")
            actual_market = "US" if symbol.endswith(".US") else "CN" if symbol.endswith((".SH", ".SZ")) else None
            if actual_market != market:
                return None
        event_date = _parse_date(getter("date"), fallback=group_date)
        event_datetime = _parse_datetime(getter("datetime"))
        name = _none_if_blank(getter("counter_name"))
        content = _none_if_blank(getter("content")) or _enum_name(getter("event_type"))
        if calendar_type == "macro" and not content:
            return None
        details = []
        for item in getter("data_kv") or []:
            item_get = item.get if isinstance(item, Mapping) else lambda key: getattr(item, key, None)
            value = item_get("value")
            if value is None:
                value = item_get("value_raw")
            details.append({"key": item_get("key"), "value": _jsonable(value)})
        event = {
            "provider": PROVIDER,
            "provider_event_id": _none_if_blank(getter("id")),
            "calendar_type": calendar_type,
            "market": market,
            "symbol": symbol,
            "counter_name": name,
            "event_type": "earnings_release" if calendar_type == "earnings" else macro_type(content),
            "event_date": event_date.isoformat(),
            "event_datetime": event_datetime.isoformat() if event_datetime else None,
            "market_session": normalize_session(getter("financial_market_time") or getter("date_type")),
            "title": (f"{symbol} {name or ''} 财报" if symbol else content)[:120],
            "content": "\n".join([content, *(f"{item['key']}: {item['value']}" for item in details)]),
            "currency": _none_if_blank(getter("currency")),
        }
        raw = {
            key: _jsonable(getter(key))
            for key in (
                "id",
                "symbol",
                "market",
                "counter_name",
                "event_type",
                "date",
                "datetime",
                "financial_market_time",
                "date_type",
                "content",
                "currency",
            )
        }
        raw["details"] = details
        return with_source(event, raw, observed_at=utc_now())

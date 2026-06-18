# -*- coding: utf-8 -*-
"""Longbridge finance calendar fetcher."""

from __future__ import annotations

import inspect
import json
import logging
import os
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from data_provider.longbridge_fetcher import _longbridge_config_kwargs, _sanitize_longbridge_env
from src.time_utils import coerce_aware_utc

logger = logging.getLogger(__name__)

PROVIDER = "longbridge"
MARKET_CALENDAR_TIMEZONE = "Asia/Shanghai"
CALENDAR_TYPE_LABELS: Dict[str, str] = {
    "earnings": "财报",
    "dividend": "分红",
    "split": "拆股",
    "ipo": "IPO",
    "macro": "宏观",
}


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


def _dumps_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, default=str)


def _parse_date(value: Any, fallback: Optional[date] = None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean_text(value)
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
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(MARKET_CALENDAR_TIMEZONE))
    return parsed.astimezone(timezone.utc)


def _normalize_market(value: Any, default: str) -> str:
    text = _enum_name(value).upper() or default
    if text.endswith(".US"):
        return "US"
    return text


def _normalize_symbol(value: Any) -> Optional[str]:
    symbol = _none_if_blank(value)
    if not symbol:
        return None
    symbol = symbol.upper()
    if symbol.endswith(".US"):
        symbol = symbol[:-3]
    return symbol or None


def _data_kv_to_list(items: Any) -> List[Dict[str, Any]]:
    if not items:
        return []
    normalized: List[Dict[str, Any]] = []
    for item in items:
        normalized.append(
            {
                "key": _none_if_blank(getattr(item, "key", None)),
                "value": _jsonable(getattr(item, "value", None)),
                "value_raw": _jsonable(getattr(item, "value_raw", None)),
                "value_type": _none_if_blank(_enum_name(getattr(item, "value_type", None))),
            }
        )
    return normalized


def build_event_title(event: Mapping[str, Any]) -> str:
    label = CALENDAR_TYPE_LABELS.get(str(event.get("calendar_type") or ""), str(event.get("calendar_type") or "日历"))
    symbol = _clean_text(event.get("symbol"))
    counter_name = _clean_text(event.get("counter_name"))
    content_or_type = _clean_text(event.get("content")) or _clean_text(event.get("event_type"))
    if symbol:
        parts = [symbol, counter_name, label, content_or_type]
    else:
        parts = [label, content_or_type]
    title = " ".join(part for part in parts if part)
    return title[:120] or label


def build_event_content(event: Mapping[str, Any]) -> str:
    data_kv = event.get("data_kv") or []
    lines = [
        f"- 类型：{CALENDAR_TYPE_LABELS.get(str(event.get('calendar_type') or ''), event.get('calendar_type') or '-')}",
        f"- 股票代码：{event.get('symbol') or '-'}",
        f"- 公司名称：{event.get('counter_name') or '-'}",
        f"- 市场：{event.get('market') or '-'}",
        f"- 事件日期：{event.get('event_date') or '-'}",
        f"- 事件时间：{event.get('event_datetime') or event.get('financial_market_time') or '-'}",
        f"- 重要性 star：{event.get('star') if event.get('star') is not None else '-'}",
        f"- 事件内容：{event.get('content') or event.get('event_type') or '-'}",
    ]
    if data_kv:
        lines.extend(["", "### 明细"])
        for item in data_kv:
            key = item.get("key") or "-"
            value = item.get("value")
            if value is None:
                value = item.get("value_raw")
            lines.append(f"- {key}：{value if value is not None else '-'}")
    lines.extend(["", f"- 来源 provider：{event.get('provider') or PROVIDER}"])
    return "\n".join(lines)


class LongbridgeCalendarFetcher:
    """Fetch and normalize Longbridge finance calendar events."""

    _CATEGORY_BY_TYPE: Dict[str, str] = {
        "earnings": "Report",
        "dividend": "Dividend",
        "split": "Split",
        "ipo": "Ipo",
        "macro": "MacroData",
    }

    def __init__(self) -> None:
        self._ctx = None
        self._config = None

    def _has_credentials(self) -> bool:
        try:
            from src.config import get_config

            config = get_config()
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
            from src.config import get_config

            app_config = get_config()
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

    def _resolve_market(self, market: str) -> Any:
        from longbridge.openapi import Market

        return getattr(Market, market.upper(), market)

    def fetch_earnings_calendar(self, start: date, end: date, market: str) -> List[Dict[str, Any]]:
        return self.fetch_calendar("earnings", start, end, market)

    def fetch_dividend_calendar(self, start: date, end: date, market: str) -> List[Dict[str, Any]]:
        return self.fetch_calendar("dividend", start, end, market)

    def fetch_split_calendar(self, start: date, end: date, market: str) -> List[Dict[str, Any]]:
        return self.fetch_calendar("split", start, end, market)

    def fetch_ipo_calendar(self, start: date, end: date, market: str) -> List[Dict[str, Any]]:
        return self.fetch_calendar("ipo", start, end, market)

    def fetch_macro_calendar(self, start: date, end: date, market: str) -> List[Dict[str, Any]]:
        return self.fetch_calendar("macro", start, end, market)

    def fetch_calendar(self, calendar_type: str, start: date, end: date, market: str) -> List[Dict[str, Any]]:
        ctx = self._get_ctx()
        method = getattr(ctx, "finance_calendar", None)
        if not callable(method):
            raise RuntimeError("Longbridge CalendarContext.finance_calendar is not available")

        try:
            logger.debug("Longbridge finance_calendar signature: %s", inspect.signature(method))
        except Exception:
            pass

        response = method(self._resolve_category(calendar_type), start, end, self._resolve_market(market))
        return self.normalize_response(response, calendar_type=calendar_type, market=market)

    def normalize_response(self, response: Any, *, calendar_type: str, market: str) -> List[Dict[str, Any]]:
        groups = getattr(response, "list", None)
        if groups is None and isinstance(response, Mapping):
            groups = response.get("list")
        if groups is None:
            groups = response or []

        events: List[Dict[str, Any]] = []
        for group in groups:
            group_date = _parse_date(getattr(group, "date", None) if not isinstance(group, Mapping) else group.get("date"))
            infos = getattr(group, "infos", None) if not isinstance(group, Mapping) else group.get("infos")
            for info in infos or []:
                event = self.normalize_info(info, calendar_type=calendar_type, market=market, group_date=group_date)
                events.append(event)
        return events

    def normalize_info(
        self,
        info: Any,
        *,
        calendar_type: str,
        market: str,
        group_date: date,
    ) -> Dict[str, Any]:
        getter = info.get if isinstance(info, Mapping) else lambda key, default=None: getattr(info, key, default)
        event_date = _parse_date(getter("date", None), fallback=group_date)
        event_datetime = _parse_datetime(getter("datetime", None))
        data_kv = _data_kv_to_list(getter("data_kv", None))
        event: Dict[str, Any] = {
            "provider": PROVIDER,
            "calendar_type": calendar_type,
            "provider_event_id": _none_if_blank(getter("id", None)),
            "symbol": _normalize_symbol(getter("symbol", None)),
            "market": _normalize_market(getter("market", None), market),
            "counter_name": _none_if_blank(getter("counter_name", None)),
            "event_type": _none_if_blank(_enum_name(getter("event_type", None))),
            "activity_type": _none_if_blank(_enum_name(getter("activity_type", None))),
            "event_date": event_date.isoformat(),
            "event_datetime": event_datetime.isoformat() if event_datetime else None,
            "date_type": _none_if_blank(_enum_name(getter("date_type", None))),
            "financial_market_time": _none_if_blank(getter("financial_market_time", None)),
            "content": _none_if_blank(getter("content", None)) or "",
            "star": getter("star", None),
            "currency": _none_if_blank(getter("currency", None)),
            "data_kv": data_kv,
            "raw_payload_json": _dumps_json(info),
        }
        try:
            event["star"] = int(event["star"]) if event["star"] is not None else None
        except (TypeError, ValueError):
            event["star"] = None
        event["title"] = build_event_title(event)
        event["content_markdown"] = build_event_content(event)
        event["data_kv_json"] = _dumps_json(data_kv)
        return event

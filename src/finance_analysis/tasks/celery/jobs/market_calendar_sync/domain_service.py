# -*- coding: utf-8 -*-
"""Market finance calendar sync service."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from finance_analysis.core.time import utc_now
from finance_analysis.database.models import FinanceEvent
from finance_analysis.database.repositories.market_calendar_event import (
    FinanceEventUpsertResult,
    MarketCalendarEventRepo,
    notification_fingerprint,
)
from finance_analysis.database.repositories.universe import UniverseResolver
from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.market_calendar.events import CALENDAR_TYPE_LABELS, CALENDAR_TYPES, merge_events, source_payloads

logger = logging.getLogger(__name__)

MARKET_CALENDAR_LOOKAHEAD_DAYS = 30
EARNINGS_UNIVERSES = {"US": "us_sp500", "CN": "cn_csi300"}
MARKET_CALENDAR_TIMEZONE = "Asia/Shanghai"
MARKET_CALENDAR_NOTIFICATION_DAYS = MARKET_CALENDAR_LOOKAHEAD_DAYS

IMPORTANCE_RELEVANT_FIELDS = {
    "calendar_type",
    "symbol",
    "counter_name",
    "event_type",
    "event_date",
    "event_datetime",
    "market_session",
    "eps_estimate",
    "reported_eps",
    "eps_surprise_pct",
    "title",
    "content",
}


@dataclass
class MarketCalendarSyncSummary:
    started_at: datetime
    finished_at: datetime
    start_date: date
    end_date: date
    markets: Sequence[str]
    fetched_count_by_type: Dict[str, int] = field(default_factory=dict)
    source_stats: Dict[str, dict] = field(default_factory=dict)
    merged_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    skipped_duplicate_count: int = 0
    notification_sent_count: int = 0
    errors: List[str] = field(default_factory=list)
    new_or_changed_important_events: List[FinanceEvent] = field(default_factory=list)
    focus_events: List[FinanceEvent] = field(default_factory=list)
    importance_candidate_ids: List[int] = field(default_factory=list)

    @property
    def fetched_total_count(self) -> int:
        return sum(self.fetched_count_by_type.values())

    @property
    def all_interfaces_failed(self) -> bool:
        if self.fetched_total_count:
            return False
        core = [stats for key, stats in self.source_stats.items() if key.endswith(":US")]
        return bool(core) and not any(stats["pages_succeeded"] for stats in core)

    @property
    def all_writes_failed(self) -> bool:
        return self.merged_count > 0 and not (self.inserted_count + self.updated_count + self.skipped_duplicate_count)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "markets": list(self.markets),
            "source_stats": self.source_stats,
            "merged_count": self.merged_count,
            "all_writes_failed": self.all_writes_failed,
            "fetched_count_by_type": dict(self.fetched_count_by_type),
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "skipped_duplicate_count": self.skipped_duplicate_count,
            "notification_sent_count": self.notification_sent_count,
            "errors": list(self.errors),
            "importance_candidate_ids": list(self.importance_candidate_ids),
            "all_interfaces_failed": self.all_interfaces_failed,
        }


def scheduler_now(now: Optional[datetime] = None) -> datetime:
    tz = ZoneInfo(MARKET_CALENDAR_TIMEZONE)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def query_date_range(now: Optional[datetime] = None) -> tuple[date, date]:
    local_now = scheduler_now(now)
    start = local_now.date()
    return start, start + timedelta(days=MARKET_CALENDAR_LOOKAHEAD_DAYS)


def normalize_watch_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if normalized.endswith(".US"):
        normalized = normalized[:-3]
    if normalized.startswith("$"):
        normalized = normalized[1:]
    return normalized


def _event_symbol(event: FinanceEvent) -> str:
    return normalize_watch_symbol(getattr(event, "symbol", "") or "")


def _event_date(event: FinanceEvent) -> date:
    value = getattr(event, "event_date", None)
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _event_importance_score(event: FinanceEvent) -> Optional[int]:
    value = getattr(event, "importance_score", None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _calendar_type_rank(calendar_type: str) -> int:
    return {"earnings": 0, "macro": 1}.get(calendar_type, 9)


def sort_focus_events(events: Sequence[FinanceEvent], watch_symbols: Sequence[str]) -> List[FinanceEvent]:
    watch = {normalize_watch_symbol(symbol) for symbol in watch_symbols if normalize_watch_symbol(symbol)}

    def _key(event: FinanceEvent) -> tuple[int, int, int, int, date, str]:
        symbol = _event_symbol(event)
        calendar_type = str(getattr(event, "calendar_type", "") or "")
        score = _event_importance_score(event)
        return (
            0 if score is not None else 1,
            -(score or 0),
            0 if symbol in watch else 1,
            _calendar_type_rank(calendar_type),
            _event_date(event),
            str(getattr(event, "title", "") or ""),
        )

    return sorted(events, key=_key)


def is_important_for_notification(event: FinanceEvent, watch_symbols: Sequence[str], today: date) -> bool:
    return event.calendar_type in CALENDAR_TYPES and today <= _event_date(event) <= (
        today + timedelta(days=MARKET_CALENDAR_NOTIFICATION_DAYS)
    )


def render_event_line(event: FinanceEvent) -> str:
    label = CALENDAR_TYPE_LABELS.get(str(getattr(event, "calendar_type", "") or ""), "财经事件")
    symbol = _event_symbol(event)
    prefix = f"{symbol} {label}" if symbol else label
    score = _event_importance_score(event)
    importance_text = f"，重要性 {score}/10" if score is not None else ""
    event_time = getattr(event, "event_datetime", None) or getattr(event, "market_session", None) or ""
    time_text = f" {event_time}" if event_time else ""
    return (
        f"- {prefix}：{_event_date(event).isoformat()}{time_text}" f"{importance_text}，{getattr(event, 'title', '')}"
    )


def render_notification(events: Sequence[FinanceEvent], start_date: date, end_date: date) -> str:
    lines = [
        f"【财经日历】新增或时间调整 {len(events)} 个事件",
        f"范围：{start_date.isoformat()} 至 {end_date.isoformat()}",
        "",
    ]
    lines.extend(render_event_line(event) for event in events[:20])
    if len(events) > 20:
        lines.append(f"- ……另有 {len(events) - 20} 个事件。")
    return "\n".join(lines).strip()


class MarketCalendarSyncService:
    def __init__(
        self,
        *,
        sources: Optional[Dict[str, Any]] = None,
        repo: Optional[MarketCalendarEventRepo] = None,
        universe_resolver: Optional[Any] = None,
        notifier_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.sources = sources
        self.repo = repo or MarketCalendarEventRepo()
        self.universe_resolver = universe_resolver or UniverseResolver()
        self.notifier_factory = notifier_factory

    def run(self, now: Optional[datetime] = None) -> MarketCalendarSyncSummary:
        started_at = scheduler_now(now)
        start_date, end_date = query_date_range(started_at)
        summary = MarketCalendarSyncSummary(
            started_at=started_at,
            finished_at=started_at,
            start_date=start_date,
            end_date=end_date,
            markets=("US", "CN"),
        )
        sources = self.sources if self.sources is not None else MarketDataService().get_calendar_sources()
        watch_symbols = self._watch_symbols()
        upsert_results = []
        for calendar_type, market in (("earnings", "US"), ("earnings", "CN"), ("macro", "US")):
            symbols = set()
            if calendar_type == "earnings":
                try:
                    symbols = {
                        item.code for item in self.universe_resolver.resolve_universe(EARNINGS_UNIVERSES[market])
                    }
                    if not symbols:
                        summary.errors.append(f"empty Universe: {EARNINGS_UNIVERSES[market]}")
                except Exception as exc:
                    summary.errors.append(f"Universe {market}: {exc}")
                    logger.warning("Calendar Universe unavailable: %s %s", market, exc)
            events = []
            for provider in ("yfinance", "longbridge"):
                key = f"{provider}:{calendar_type}:{market}"
                stats = dict(
                    fetched=0,
                    accepted=0,
                    merged=0,
                    inserted=0,
                    updated=0,
                    errors=0,
                    pages_succeeded=0,
                    skipped=0,
                    universe_size=len(symbols),
                )
                summary.source_stats[key] = stats
                try:
                    result = getattr(sources[provider], f"fetch_{calendar_type}_calendar")(
                        start_date,
                        end_date,
                        market,
                        symbols=symbols,
                    )
                    stats.update(
                        fetched=result.fetched,
                        pages_succeeded=result.pages_succeeded,
                        skipped=result.skipped,
                        errors=len(result.errors),
                    )
                    summary.errors.extend(f"{key}: {error}" for error in result.errors)
                    for event in result.events:
                        try:
                            valid = (
                                event["calendar_type"] == calendar_type
                                and event["market"] == market
                                and start_date <= date.fromisoformat(str(event["event_date"])[:10]) <= end_date
                                and (calendar_type == "macro" or event.get("symbol") in symbols)
                            )
                            if valid:
                                events.append(event)
                                stats["accepted"] += 1
                            else:
                                stats["skipped"] += 1
                        except Exception as exc:
                            stats["errors"] += 1
                            summary.errors.append(f"{key} invalid event: {exc}")
                except Exception as exc:
                    stats["errors"] += 1
                    summary.errors.append(f"{key}: {exc}")
                    logger.warning("Calendar source failed: %s %s", key, exc)
                summary.fetched_count_by_type[calendar_type] = (
                    summary.fetched_count_by_type.get(calendar_type, 0) + stats["accepted"]
                )
            for event in merge_events(events, as_of=start_date):
                summary.merged_count += 1
                contributors = [
                    summary.source_stats[f"{provider}:{calendar_type}:{market}"]
                    for provider in ("yfinance", "longbridge")
                    if provider in source_payloads(event)
                ]
                for stats in contributors:
                    stats["merged"] += 1
                if source_payloads(event).get("conflicts"):
                    logger.debug(
                        "Calendar source conflict: %s %s",
                        event.get("symbol") or event["title"],
                        source_payloads(event)["conflicts"],
                    )
                try:
                    result = self.repo.upsert_event(event, as_of=start_date)
                    upsert_results.append(result)
                    if result.created:
                        summary.inserted_count += 1
                    elif result.updated:
                        summary.updated_count += 1
                    else:
                        summary.skipped_duplicate_count += 1
                    for stats in contributors:
                        stats["inserted"] += int(result.created)
                        stats["updated"] += int(result.updated)
                    if self._needs_importance_score(result) and result.event.id not in summary.importance_candidate_ids:
                        summary.importance_candidate_ids.append(result.event.id)
                except Exception as exc:
                    summary.errors.append(f"{calendar_type}:{market} upsert: {exc}")
                    for stats in contributors:
                        stats["errors"] += 1
                    logger.warning("Calendar upsert failed: %s", exc, exc_info=True)
        candidates = self._notification_candidates(upsert_results, watch_symbols, start_date)
        summary.new_or_changed_important_events = candidates
        summary.notification_sent_count = self._send_notification(candidates, start_date)
        try:
            summary.focus_events = sort_focus_events(
                self.repo.list_events_by_date_range(start_date, end_date),
                watch_symbols,
            )[:30]
        except Exception as exc:
            summary.errors.append(f"focus_events: {exc}")
        summary.finished_at = scheduler_now()
        logger.info("财经日历同步结果: %s", summary.to_dict())
        return summary

    def _watch_symbols(self) -> List[str]:
        try:
            from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market

            return [
                normalize_watch_symbol(symbol)
                for market in ("US", "CN")
                for symbol in get_watch_list_codes_by_market(market)
            ]
        except Exception as exc:
            logger.warning("读取自选列表失败: %s", exc, exc_info=True)
            return []

    def _notification_candidates(
        self,
        upsert_results: Sequence[FinanceEventUpsertResult],
        watch_symbols: Sequence[str],
        today: date,
    ) -> List[FinanceEvent]:
        selected: List[FinanceEvent] = []
        for result in upsert_results:
            event = result.event
            if not (
                result.created or {"event_date", "event_datetime", "market_session"}.intersection(result.changed_fields)
            ):
                continue
            if any(item.id == event.id for item in selected):
                continue
            if not is_important_for_notification(event, watch_symbols, today):
                continue
            fingerprint = notification_fingerprint(
                {
                    "calendar_type": event.calendar_type,
                    "symbol": event.symbol,
                    "event_date": event.event_date,
                    "event_datetime": event.event_datetime,
                    "title": event.title,
                    "content": event.content,
                    "market_session": event.market_session,
                }
            )
            if getattr(event, "notification_fingerprint", None) == fingerprint:
                continue
            setattr(event, "_pending_notification_fingerprint", fingerprint)
            selected.append(event)
        return sort_focus_events(selected, watch_symbols)

    def _send_notification(self, events: Sequence[FinanceEvent], start_date: date) -> int:
        if not events:
            return 0
        end_date = start_date + timedelta(days=MARKET_CALENDAR_NOTIFICATION_DAYS)
        digest = hashlib.sha256(
            "|".join(
                f"{event.id}:{getattr(event, '_pending_notification_fingerprint', '')}" for event in events
            ).encode()
        ).hexdigest()
        try:
            notifier = self._notifier()
            sent = notifier.send(
                render_notification(events, start_date, end_date),
                email_stock_codes=[_event_symbol(event) for event in events if _event_symbol(event)],
                route_type="alert",
                severity="info",
                dedup_key=f"market_calendar:{digest}",
                cooldown_key=f"market_calendar:{digest}",
            )
        except Exception as exc:
            logger.warning("发送财经日历通知失败: %s", exc, exc_info=True)
            return 0
        if not sent:
            logger.info("财经日历通知未发送或无可用渠道")
            return 0
        notified_at = utc_now()
        marked = 0
        for event in events:
            fingerprint = getattr(event, "_pending_notification_fingerprint", None)
            try:
                if fingerprint and self.repo.mark_notified(int(event.id), fingerprint, notified_at=notified_at):
                    marked += 1
            except Exception as exc:
                logger.warning("财经日历通知标记失败: event_id=%s error=%s", event.id, exc)
        return marked

    def _notifier(self) -> Any:
        if self.notifier_factory is not None:
            return self.notifier_factory()
        from finance_analysis.notification.service import NotificationService

        return NotificationService()

    def _needs_importance_score(self, result: FinanceEventUpsertResult) -> bool:
        if result.created or result.event.importance_score is None:
            return True
        return bool(IMPORTANCE_RELEVANT_FIELDS.intersection(result.changed_fields))

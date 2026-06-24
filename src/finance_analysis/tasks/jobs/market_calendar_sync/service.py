# -*- coding: utf-8 -*-
"""Market finance calendar sync service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.providers.longbridge.calendar import CALENDAR_TYPE_LABELS, LongbridgeCalendarFetcher
from finance_analysis.database.models import FinanceEvent
from finance_analysis.database.repositories.market_calendar_event import (
    FinanceEventUpsertResult,
    MarketCalendarEventRepo,
    notification_fingerprint,
)
from finance_analysis.core.time import utc_now

logger = logging.getLogger(__name__)

MARKET_CALENDAR_LOOKAHEAD_DAYS = 30
MARKET_CALENDAR_MARKET = "US"
MARKET_CALENDAR_TIMEZONE = "Asia/Shanghai"
MARKET_CALENDAR_NOTIFICATION_DAYS = 14
MARKET_CALENDAR_DIVIDEND_SPLIT_IPO_NOTIFICATION_DAYS = 3

CALENDAR_TYPES: Sequence[str] = ("earnings", "dividend", "split", "ipo", "macro")
IMPORTANCE_RELEVANT_FIELDS = {
    "calendar_type",
    "symbol",
    "counter_name",
    "event_type",
    "activity_type",
    "event_date",
    "event_datetime",
    "title",
    "content",
    "star",
    "data_kv_json",
}


@dataclass
class MarketCalendarSyncSummary:
    started_at: datetime
    finished_at: datetime
    start_date: date
    end_date: date
    market: str
    fetched_count_by_type: Dict[str, int] = field(default_factory=dict)
    inserted_count: int = 0
    updated_count: int = 0
    skipped_duplicate_count: int = 0
    notification_sent_count: int = 0
    errors: List[str] = field(default_factory=list)
    new_or_changed_important_events: List[FinanceEvent] = field(default_factory=list)
    focus_events: List[FinanceEvent] = field(default_factory=list)
    importance_candidate_ids: List[int] = field(default_factory=list)
    calendar_id: Optional[int] = None

    @property
    def fetched_total_count(self) -> int:
        return sum(self.fetched_count_by_type.values())

    @property
    def all_interfaces_failed(self) -> bool:
        return len(self.errors) >= len(CALENDAR_TYPES) and self.fetched_total_count == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "market": self.market,
            "fetched_count_by_type": dict(self.fetched_count_by_type),
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "skipped_duplicate_count": self.skipped_duplicate_count,
            "notification_sent_count": self.notification_sent_count,
            "errors": list(self.errors),
            "importance_candidate_ids": list(self.importance_candidate_ids),
            "calendar_id": self.calendar_id,
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


def _event_star(event: FinanceEvent) -> int:
    try:
        return int(getattr(event, "star", None) or 0)
    except (TypeError, ValueError):
        return 0


def _event_importance_score(event: FinanceEvent) -> Optional[int]:
    value = getattr(event, "importance_score", None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _calendar_type_rank(calendar_type: str) -> int:
    return {"earnings": 0, "macro": 1, "dividend": 2, "split": 3, "ipo": 4}.get(calendar_type, 9)


def sort_focus_events(events: Sequence[FinanceEvent], watch_symbols: Sequence[str]) -> List[FinanceEvent]:
    watch = {normalize_watch_symbol(symbol) for symbol in watch_symbols if normalize_watch_symbol(symbol)}

    def _key(event: FinanceEvent) -> tuple[int, int, int, int, int, date, str]:
        symbol = _event_symbol(event)
        calendar_type = str(getattr(event, "calendar_type", "") or "")
        score = _event_importance_score(event)
        return (
            0 if score is not None else 1,
            -(score or 0),
            0 if symbol in watch else 1,
            -_event_star(event),
            _calendar_type_rank(calendar_type),
            _event_date(event),
            str(getattr(event, "title", "") or ""),
        )

    return sorted(events, key=_key)


def is_important_for_notification(event: FinanceEvent, watch_symbols: Sequence[str], today: date) -> bool:
    calendar_type = str(getattr(event, "calendar_type", "") or "")
    if calendar_type in {"earnings", "macro"}:
        return True
    if _event_star(event) >= 2:
        return True
    watch = {normalize_watch_symbol(symbol) for symbol in watch_symbols if normalize_watch_symbol(symbol)}
    if _event_symbol(event) in watch:
        return True
    if calendar_type in {"dividend", "split", "ipo"}:
        delta_days = (_event_date(event) - today).days
        return 0 <= delta_days <= MARKET_CALENDAR_DIVIDEND_SPLIT_IPO_NOTIFICATION_DAYS
    return False


def render_event_line(event: FinanceEvent) -> str:
    label = CALENDAR_TYPE_LABELS.get(str(getattr(event, "calendar_type", "") or ""), "财经事件")
    symbol = _event_symbol(event)
    prefix = f"{symbol} {label}" if symbol else label
    star = _event_star(event)
    score = _event_importance_score(event)
    importance_text = f"，重要性 {score}/10" if score is not None else ""
    star_text = f"，provider star={star}" if star else ""
    event_time = getattr(event, "event_datetime", None) or getattr(event, "financial_market_time", None) or ""
    time_text = f" {event_time}" if isinstance(event_time, str) and event_time else ""
    return (
        f"- {prefix}：{_event_date(event).isoformat()}{time_text}"
        f"{importance_text}{star_text}，{getattr(event, 'title', '')}"
    )


def render_calendar_content(summary: MarketCalendarSyncSummary) -> str:
    elapsed = (summary.finished_at - summary.started_at).total_seconds()
    lines = [
        "## 财经日历更新",
        "",
        f"- 执行状态：{'失败' if summary.all_interfaces_failed else '完成'}",
        f"- 开始时间：{summary.started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 结束时间：{summary.finished_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 耗时：{elapsed:.2f} 秒",
        f"- 查询范围：{summary.start_date.isoformat()} 至 {summary.end_date.isoformat()}",
        f"- 市场：{summary.market}",
        "",
        "### 抓取数量",
    ]
    for calendar_type in CALENDAR_TYPES:
        label = CALENDAR_TYPE_LABELS.get(calendar_type, calendar_type)
        lines.append(f"- {label}：{summary.fetched_count_by_type.get(calendar_type, 0)}")

    lines.extend(
        [
            "",
            "### 入库结果",
            f"- 新增事件数量：{summary.inserted_count}",
            f"- 更新事件数量：{summary.updated_count}",
            f"- 跳过重复数量：{summary.skipped_duplicate_count}",
            f"- 通知事件数量：{summary.notification_sent_count}",
        ]
    )

    if summary.errors:
        lines.extend(["", "### 失败接口列表", "", *[f"- {item}" for item in summary.errors]])
    else:
        lines.extend(["", "### 失败接口列表", "", "- 无"])

    lines.extend(["", "### 未来 14 天重点事件", ""])
    if summary.focus_events:
        focus = summary.focus_events[:30]
        lines.extend(render_event_line(event) for event in focus)
        remaining = len(summary.focus_events) - len(focus)
        if remaining > 0:
            lines.append(f"- ……另有 {remaining} 条重点事件未展示。")
    else:
        lines.append("- 无")

    return "\n".join(lines).strip()


def render_notification(events: Sequence[FinanceEvent], start_date: date, end_date: date) -> str:
    lines = [
        f"【财经日历】未来 14 天新增 {len(events)} 个事件",
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
        fetcher: Optional[LongbridgeCalendarFetcher] = None,
        repo: Optional[MarketCalendarEventRepo] = None,
        calendar_repo: Optional[Any] = None,
        user_repo: Optional[Any] = None,
        notifier_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.fetcher = fetcher or LongbridgeCalendarFetcher()
        self.repo = repo or MarketCalendarEventRepo()
        self.calendar_repo = calendar_repo
        self.user_repo = user_repo
        self.notifier_factory = notifier_factory

    def run(self, now: Optional[datetime] = None) -> MarketCalendarSyncSummary:
        started_at = scheduler_now(now)
        start_date, end_date = query_date_range(started_at)
        summary = MarketCalendarSyncSummary(
            started_at=started_at,
            finished_at=started_at,
            start_date=start_date,
            end_date=end_date,
            market=MARKET_CALENDAR_MARKET,
        )
        watch_symbols = self._watch_symbols()
        upsert_results: List[FinanceEventUpsertResult] = []

        for calendar_type in CALENDAR_TYPES:
            fetch_method = getattr(self.fetcher, f"fetch_{calendar_type}_calendar")
            try:
                events = fetch_method(start_date, end_date, MARKET_CALENDAR_MARKET)
            except Exception as exc:
                message = f"{calendar_type}: {exc}"
                logger.warning("财经日历接口失败 %s", message, exc_info=True)
                summary.errors.append(message)
                summary.fetched_count_by_type[calendar_type] = 0
                continue

            summary.fetched_count_by_type[calendar_type] = len(events)
            if not events:
                logger.info("财经日历接口返回空数据: type=%s", calendar_type)
            for event in events:
                try:
                    result = self.repo.upsert_event(event)
                except Exception as exc:
                    message = f"{calendar_type} upsert failed: {exc}"
                    logger.warning("财经日历事件入库失败 %s", message, exc_info=True)
                    summary.errors.append(message)
                    continue
                upsert_results.append(result)
                if result.created:
                    summary.inserted_count += 1
                elif result.updated:
                    summary.updated_count += 1
                else:
                    summary.skipped_duplicate_count += 1
                if self._needs_importance_score(result):
                    event_id = int(getattr(result.event, "id", 0) or 0)
                    if event_id and event_id not in summary.importance_candidate_ids:
                        summary.importance_candidate_ids.append(event_id)

        notification_candidates = self._notification_candidates(upsert_results, watch_symbols, start_date)
        summary.new_or_changed_important_events = notification_candidates
        summary.notification_sent_count = self._send_notification(notification_candidates, start_date)

        focus_end_date = start_date + timedelta(days=MARKET_CALENDAR_NOTIFICATION_DAYS)
        try:
            focus_events = self.repo.list_events_by_date_range(start_date, focus_end_date, market=MARKET_CALENDAR_MARKET)
        except Exception as exc:
            logger.warning("读取财经日历重点事件失败: %s", exc, exc_info=True)
            summary.errors.append(f"focus_events: {exc}")
            focus_events = []
        summary.focus_events = sort_focus_events(focus_events, watch_symbols)[:30]
        summary.finished_at = scheduler_now()
        summary.calendar_id = self._record_calendar(summary)

        logger.info(
            "财经日历任务完成: fetched=%s inserted=%s updated=%s duplicate=%s notify=%s errors=%s",
            summary.fetched_count_by_type,
            summary.inserted_count,
            summary.updated_count,
            summary.skipped_duplicate_count,
            summary.notification_sent_count,
            len(summary.errors),
        )
        return summary

    def _watch_symbols(self) -> List[str]:
        try:
            from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market

            return [normalize_watch_symbol(symbol) for symbol in get_watch_list_codes_by_market("US")]
        except Exception as exc:
            logger.warning("读取美股自选列表失败: %s", exc, exc_info=True)
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
            if not (result.created or result.changed_fields):
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
                    "event_type": event.event_type,
                    "activity_type": event.activity_type,
                    "star": event.star,
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
        try:
            notifier = self._notifier()
            sent = notifier.send(
                render_notification(events, start_date, end_date),
                email_stock_codes=[_event_symbol(event) for event in events if _event_symbol(event)],
                route_type="alert",
                severity="info",
                dedup_key=f"market_calendar:{start_date.isoformat()}:{len(events)}",
                cooldown_key="market_calendar",
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
            if fingerprint and self.repo.mark_notified(int(event.id), fingerprint, notified_at=notified_at):
                marked += 1
        return marked

    def _notifier(self) -> Any:
        if self.notifier_factory is not None:
            return self.notifier_factory()
        from finance_analysis.notification.service import NotificationService

        return NotificationService()

    def _needs_importance_score(self, result: FinanceEventUpsertResult) -> bool:
        if result.created:
            return True
        return bool(IMPORTANCE_RELEVANT_FIELDS.intersection(result.changed_fields))

    def _record_calendar(self, summary: MarketCalendarSyncSummary) -> Optional[int]:
        try:
            calendar_repo = self.calendar_repo
            if calendar_repo is None:
                from finance_analysis.database.repositories.calendar import CalendarRepo

                calendar_repo = CalendarRepo()
            user_repo = self.user_repo
            if user_repo is None:
                from finance_analysis.database.repositories.user import UserRepository

                user_repo = UserRepository()
            uid = user_repo.ensure_default_admin()
            title = f"财经日历更新完成：新增 {summary.inserted_count} / 总计 {summary.fetched_total_count}"
            if summary.all_interfaces_failed:
                title = f"财经日历更新失败：新增 {summary.inserted_count} / 总计 {summary.fetched_total_count}"
            entry = calendar_repo.create(
                uid=uid,
                time=summary.finished_at,
                title=title[:120],
                content=render_calendar_content(summary),
                type="scheduled_market_calendar",
            )
            return int(getattr(entry, "id", 0) or 0)
        except Exception as exc:
            logger.warning("写入财经日历摘要失败: %s", exc, exc_info=True)
            return None

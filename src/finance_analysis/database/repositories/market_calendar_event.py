# -*- coding: utf-8 -*-
"""Repository for structured market finance calendar events."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from finance_analysis.database.models import FinanceEvent
from finance_analysis.database.base import ensure_aware_datetime
from finance_analysis.database.session import DatabaseManager
from finance_analysis.core.time import utc_now


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _date_value(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _datetime_value(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_aware_datetime(value)
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _digest(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_event_key(event: Mapping[str, Any]) -> str:
    """Build a stable unique identity for a provider calendar event."""
    provider = _clean(event.get("provider")).lower() or "unknown"
    calendar_type = _clean(event.get("calendar_type")).lower()
    provider_event_id = _clean(event.get("provider_event_id"))
    if provider_event_id:
        return f"{provider}:{calendar_type}:id:{_digest(provider_event_id, 32)}"

    content_identity = _clean(event.get("title")) or _clean(event.get("content")) or _clean(event.get("content_markdown"))
    content_hash = _digest(content_identity.lower(), 32)
    parts = [
        provider,
        calendar_type,
        _clean(event.get("market")).upper(),
        _clean(event.get("symbol")).upper(),
        _date_value(event.get("event_date")).isoformat(),
        _clean(event.get("event_type")).lower(),
        _clean(event.get("activity_type")).lower(),
        content_hash,
    ]
    return "fallback:" + _digest("|".join(parts), 48)


def notification_fingerprint(event: Mapping[str, Any]) -> str:
    payload = {
        "calendar_type": _clean(event.get("calendar_type")).lower(),
        "symbol": _clean(event.get("symbol")).upper(),
        "event_date": _date_value(event.get("event_date")).isoformat(),
        "event_datetime": _clean(event.get("event_datetime")),
        "title": _clean(event.get("title")),
        "content": _clean(event.get("content")),
        "event_type": _clean(event.get("event_type")),
        "activity_type": _clean(event.get("activity_type")),
        "star": event.get("star"),
    }
    return _digest(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), 48)


def _sort_events_for_display(events: List[FinanceEvent]) -> List[FinanceEvent]:
    def _importance_rank(event: FinanceEvent) -> tuple[int, int]:
        score = getattr(event, "importance_score", None)
        if score is None:
            return (1, 0)
        try:
            return (0, -int(score))
        except (TypeError, ValueError):
            return (1, 0)

    def _star_rank(event: FinanceEvent) -> tuple[int, int]:
        star = getattr(event, "star", None)
        if star is None:
            return (1, 0)
        try:
            return (0, -int(star))
        except (TypeError, ValueError):
            return (1, 0)

    return sorted(
        events,
        key=lambda event: (
            *_importance_rank(event),
            *_star_rank(event),
            str(getattr(event, "calendar_type", "") or ""),
            str(getattr(event, "symbol", "") or ""),
            str(getattr(event, "title", "") or ""),
        ),
    )


@dataclass
class FinanceEventUpsertResult:
    event: FinanceEvent
    created: bool
    updated: bool
    changed_fields: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.created or bool(self.changed_fields)


class MarketCalendarEventRepo:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db()

    def upsert_event(self, event: Mapping[str, Any]) -> FinanceEventUpsertResult:
        event_key = normalize_event_key(event)
        now = utc_now()
        values = self._event_values(event, event_key=event_key, now=now)

        def _write(session: Session) -> FinanceEventUpsertResult:
            obj = session.execute(select(FinanceEvent).where(FinanceEvent.event_key == event_key)).scalars().first()
            if obj is None:
                obj = FinanceEvent(**values)
                session.add(obj)
                session.flush()
                session.refresh(obj)
                session.expunge(obj)
                return FinanceEventUpsertResult(event=obj, created=True, updated=False)

            changed_fields: List[str] = []
            mutable_values = dict(values)
            mutable_values.pop("first_seen_at", None)
            mutable_values.pop("created_at", None)
            mutable_values["last_seen_at"] = now
            mutable_values["updated_at"] = now
            for key, value in mutable_values.items():
                if getattr(obj, key) != value:
                    setattr(obj, key, value)
                    if key not in ("last_seen_at", "updated_at"):
                        changed_fields.append(key)
            session.flush()
            session.refresh(obj)
            session.expunge(obj)
            return FinanceEventUpsertResult(
                event=obj,
                created=False,
                updated=bool(changed_fields),
                changed_fields=changed_fields,
            )

        return self.db._run_write_transaction("finance_events.upsert", _write)

    def list_events_by_date(
        self,
        day: date,
        market: Optional[str] = None,
        calendar_type: Optional[str] = None,
    ) -> List[FinanceEvent]:
        with self.db.get_session() as session:
            stmt = (
                select(FinanceEvent)
                .where(FinanceEvent.event_date == day)
                .order_by(
                    FinanceEvent.importance_score.desc().nulls_last(),
                    FinanceEvent.star.desc().nulls_last(),
                    FinanceEvent.calendar_type.asc(),
                    FinanceEvent.symbol.asc(),
                    FinanceEvent.title.asc(),
                )
            )
            if market:
                stmt = stmt.where(FinanceEvent.market == market.upper())
            if calendar_type:
                stmt = stmt.where(FinanceEvent.calendar_type == calendar_type)
            rows = session.execute(stmt).scalars().all()
            for row in rows:
                session.expunge(row)
            return _sort_events_for_display(rows)

    def list_events_by_date_range(
        self,
        start: date,
        end: date,
        market: Optional[str] = None,
        calendar_type: Optional[str] = None,
    ) -> List[FinanceEvent]:
        with self.db.get_session() as session:
            stmt = (
                select(FinanceEvent)
                .where(and_(FinanceEvent.event_date >= start, FinanceEvent.event_date <= end))
                .order_by(
                    FinanceEvent.event_date.asc(),
                    FinanceEvent.importance_score.desc().nulls_last(),
                    FinanceEvent.star.desc().nulls_last(),
                    FinanceEvent.calendar_type.asc(),
                    FinanceEvent.symbol.asc(),
                    FinanceEvent.title.asc(),
                )
            )
            if market:
                stmt = stmt.where(FinanceEvent.market == market.upper())
            if calendar_type:
                stmt = stmt.where(FinanceEvent.calendar_type == calendar_type)
            rows = session.execute(stmt).scalars().all()
            for row in rows:
                session.expunge(row)
            return rows

    def list_events_by_ids(self, event_ids: List[int]) -> List[FinanceEvent]:
        ids = list(dict.fromkeys(int(event_id) for event_id in event_ids if event_id is not None))
        if not ids:
            return []
        with self.db.get_session() as session:
            rows = session.execute(select(FinanceEvent).where(FinanceEvent.id.in_(ids))).scalars().all()
            by_id = {int(row.id): row for row in rows}
            ordered = [by_id[event_id] for event_id in ids if event_id in by_id]
            for row in ordered:
                session.expunge(row)
            return ordered

    def build_digest_for_date_range(self, start: date, end: date) -> Dict[str, int]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(FinanceEvent.calendar_type, func.count())
                .where(and_(FinanceEvent.event_date >= start, FinanceEvent.event_date <= end))
                .group_by(FinanceEvent.calendar_type)
            ).all()
            return {str(calendar_type): int(count or 0) for calendar_type, count in rows}

    def mark_notified(self, event_id: int, fingerprint: str, notified_at: Optional[datetime] = None) -> bool:
        now = ensure_aware_datetime(notified_at) or utc_now()

        def _write(session: Session) -> bool:
            obj = session.get(FinanceEvent, event_id)
            if obj is None:
                return False
            obj.notified_at = now
            obj.notification_fingerprint = fingerprint
            obj.updated_at = now
            session.flush()
            return True

        return self.db._run_write_transaction("finance_events.mark_notified", _write)

    def update_importance_assessment(
        self,
        event_id: int,
        *,
        score: int,
        reason: str,
        confidence: float,
        model: Optional[str],
        prompt_version: str,
        input_hash: str,
        scored_at: datetime,
    ) -> bool:
        now = utc_now()
        scored_at = ensure_aware_datetime(scored_at) or now

        def _write(session: Session) -> bool:
            obj = session.get(FinanceEvent, int(event_id))
            if obj is None:
                return False
            obj.importance_score = int(score)
            obj.importance_reason = str(reason or "")
            obj.importance_confidence = float(confidence)
            obj.importance_model = str(model or "")[:128] or None
            obj.importance_prompt_version = str(prompt_version or "")[:32] or None
            obj.importance_input_hash = str(input_hash or "")[:64] or None
            obj.importance_scored_at = scored_at
            obj.updated_at = now
            session.flush()
            return True

        return self.db._run_write_transaction("finance_events.update_importance", _write)

    def _event_values(self, event: Mapping[str, Any], *, event_key: str, now: datetime) -> Dict[str, Any]:
        event_datetime = _datetime_value(event.get("event_datetime"))
        data_kv_json = event.get("data_kv_json")
        if data_kv_json is None:
            data_kv_json = _json_text(event.get("data_kv"))
        return {
            "provider": _clean(event.get("provider")) or "longbridge",
            "provider_event_id": _clean(event.get("provider_event_id")) or None,
            "event_key": event_key,
            "calendar_type": _clean(event.get("calendar_type")),
            "market": (_clean(event.get("market")) or "US").upper(),
            "symbol": _clean(event.get("symbol")).upper() or None,
            "counter_name": _clean(event.get("counter_name")) or None,
            "event_type": _clean(event.get("event_type")) or None,
            "activity_type": _clean(event.get("activity_type")) or None,
            "event_date": _date_value(event.get("event_date")),
            "event_datetime": event_datetime,
            "date_type": _clean(event.get("date_type")) or None,
            "financial_market_time": _clean(event.get("financial_market_time")) or None,
            "title": (_clean(event.get("title")) or "财经日历")[:120],
            "content": str(event.get("content_markdown") or event.get("content") or "").strip(),
            "star": int(event["star"]) if event.get("star") is not None else None,
            "currency": _clean(event.get("currency")) or None,
            "data_kv_json": data_kv_json,
            "raw_payload_json": _json_text(event.get("raw_payload_json")),
            "first_seen_at": now,
            "last_seen_at": now,
            "created_at": now,
            "updated_at": now,
        }

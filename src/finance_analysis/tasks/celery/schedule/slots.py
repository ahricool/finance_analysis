"""Resolve the original schedule slot when Beat publishes an intraday task."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .definitions import ScheduledTaskDefinition

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def resolve_scheduled_slot(definition: ScheduledTaskDefinition, published_at: datetime | None = None) -> datetime:
    """Return the most recent configured slot at or before message publication.

    The value is calculated in the task's market timezone by the Beat producer
    and then travels with the Celery message. Worker start time is never used.
    """

    timezone = ZoneInfo(definition.timezone)
    now = published_at or datetime.now(timezone)
    now = now.astimezone(timezone).replace(second=0, microsecond=0)
    candidates: list[datetime] = []
    for days_ago in range(8):
        candidate_date = (now - timedelta(days=days_ago)).date()
        for schedule in definition.schedules:
            if candidate_date.month not in _expand_numeric(schedule.month_of_year, 1, 12):
                continue
            if candidate_date.day not in _expand_numeric(schedule.day_of_month, 1, 31):
                continue
            if candidate_date.weekday() not in _expand_weekdays(schedule.day_of_week):
                continue
            for hour in _expand_numeric(schedule.hour, 0, 23):
                for minute in _expand_numeric(schedule.minute, 0, 59):
                    candidate = datetime.combine(candidate_date, datetime.min.time(), timezone).replace(
                        hour=hour,
                        minute=minute,
                    )
                    if candidate <= now:
                        candidates.append(candidate)
        if candidates:
            break
    if not candidates:
        raise ValueError(f"No scheduled slot found for {definition.job_id} at {now.isoformat()}")
    return max(candidates)


def _expand_numeric(expression: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for raw_part in str(expression).lower().split(","):
        part = raw_part.strip()
        if not part:
            continue
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            values.add(int(base))
            continue
        values.update(range(start, end + 1, step))
    return {value for value in values if minimum <= value <= maximum}


def _expand_weekdays(expression: str) -> set[int]:
    normalized = str(expression).strip().lower()
    if normalized == "*":
        return set(range(7))
    values: set[int] = set()
    for part in normalized.split(","):
        part = part.strip()
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = _weekday(start_text), _weekday(end_text)
            if start <= end:
                values.update(range(start, end + 1))
            else:
                values.update(range(start, 7))
                values.update(range(0, end + 1))
        else:
            values.add(_weekday(part))
    return values


def _weekday(value: str) -> int:
    if value in _WEEKDAYS:
        return _WEEKDAYS[value]
    numeric = int(value)
    return 6 if numeric == 0 else numeric - 1

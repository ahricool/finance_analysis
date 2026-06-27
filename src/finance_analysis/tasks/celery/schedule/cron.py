# -*- coding: utf-8 -*-
"""Timezone-aware Celery crontab helpers and next-run computation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from celery.schedules import crontab

_MAX_SEARCH_DAYS = 366 * 2


class LocalizedCrontab(crontab):
    """A Celery crontab pinned to an explicit IANA timezone."""

    def __init__(self, *args, tz: str = "Asia/Shanghai", **kwargs) -> None:
        self._tz_name = tz
        self._zone = ZoneInfo(tz)
        kwargs.setdefault("nowfun", self._now_in_zone)
        super().__init__(*args, **kwargs)

    def _now_in_zone(self) -> datetime:
        return datetime.now(self._zone)

    @property
    def tz(self) -> ZoneInfo:  # type: ignore[override]
        return self._zone

    @property
    def tz_name(self) -> str:
        return self._tz_name

    def __reduce__(self):
        return (
            _restore_localized_crontab,
            (
                self._orig_minute,
                self._orig_hour,
                self._orig_day_of_week,
                self._orig_day_of_month,
                self._orig_month_of_year,
                self._tz_name,
            ),
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LocalizedCrontab):
            return (
                self._tz_name == other._tz_name
                and self.month_of_year == other.month_of_year
                and self.day_of_month == other.day_of_month
                and self.day_of_week == other.day_of_week
                and self.hour == other.hour
                and self.minute == other.minute
            )
        return NotImplemented

    def __hash__(self) -> int:
        return hash(
            (
                self._tz_name,
                frozenset(self.minute),
                frozenset(self.hour),
                frozenset(self.day_of_week),
                frozenset(self.day_of_month),
                frozenset(self.month_of_year),
            )
        )


def _restore_localized_crontab(minute, hour, day_of_week, day_of_month, month_of_year, tz):
    return LocalizedCrontab(
        minute=minute,
        hour=hour,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        tz=tz,
    )


def next_run_for_crontab(
    schedule: crontab,
    tz_name: str,
    *,
    after: Optional[datetime] = None,
) -> Optional[datetime]:
    """Return the next fire time as aware UTC, strictly after ``after``."""
    zone = ZoneInfo(tz_name)
    reference = (after or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_reference = reference.astimezone(zone)
    minutes: Sequence[int] = sorted(schedule.minute)
    hours: Sequence[int] = sorted(schedule.hour)
    if not minutes or not hours:
        return None

    day = local_reference.date()
    for _ in range(_MAX_SEARCH_DAYS):
        if _day_matches(day, schedule):
            for hour in hours:
                for minute in minutes:
                    naive_local = datetime(day.year, day.month, day.day, hour, minute)
                    candidate_utc = naive_local.replace(tzinfo=zone).astimezone(timezone.utc)
                    if candidate_utc > reference:
                        return candidate_utc
        day += timedelta(days=1)
    return None


def compute_next_run(
    schedules: Iterable[crontab],
    tz_name: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """Return the earliest next fire time across all schedules as aware UTC."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates = []
    for schedule in schedules:
        zone = getattr(schedule, "tz_name", None) or tz_name
        candidate = next_run_for_crontab(schedule, zone, after=reference)
        if candidate is not None:
            candidates.append(candidate)
    return min(candidates) if candidates else None


def _day_matches(day, schedule: crontab) -> bool:
    return (
        day.month in schedule.month_of_year
        and day.day in schedule.day_of_month
        and (day.isoweekday() % 7) in schedule.day_of_week
    )


__all__ = ["LocalizedCrontab", "compute_next_run", "next_run_for_crontab"]

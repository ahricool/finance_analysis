"""Shared helpers for periodic task services."""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from finance_analysis.tasks.celery.schedule import SCHEDULE_TIMEZONE

logger = logging.getLogger(__name__)
INTRADAY_START_DELAY_MAX_SECONDS = 5.0


def scheduled_now() -> datetime:
    return datetime.now(ZoneInfo(SCHEDULE_TIMEZONE))


def sleep_random_start_delay(
    *,
    task_name: str,
    max_seconds: float = INTRADAY_START_DELAY_MAX_SECONDS,
) -> float:
    if max_seconds <= 0:
        return 0.0
    delay = random.uniform(0.0, max_seconds)
    logger.info("%s启动前随机延迟 %.2f 秒", task_name, delay)
    time.sleep(delay)
    return delay


def resolve_report_type(config: Any):
    from finance_analysis.reporting.types import ReportType

    report_type = str(getattr(config, "report_type", "simple") or "simple").lower()
    if report_type == "brief":
        return ReportType.BRIEF
    if report_type == "full":
        return ReportType.FULL
    return ReportType.SIMPLE


__all__ = [
    "INTRADAY_START_DELAY_MAX_SECONDS",
    "resolve_report_type",
    "scheduled_now",
    "sleep_random_start_delay",
]

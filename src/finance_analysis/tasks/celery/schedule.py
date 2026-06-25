# -*- coding: utf-8 -*-
"""Single source of truth for code-defined periodic tasks.

This registry drives every scheduling concern in one place:

* the Celery Beat ``beat_schedule`` (one entry per cron window);
* ``task_routes`` and the set of worker queues;
* the task-center listing, manual execution, and next-run display.

Each :class:`ScheduledTaskDefinition` keeps the stable ``job_id`` and
``task_type`` used by historical :class:`TaskRecord` rows, plus the Celery task
name that actually performs the work. Schedules are stored as structured
:class:`CronSchedule` entries so the same definition produces both the live
Celery ``crontab`` objects and the timezone-aware next-run computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from celery.schedules import crontab

from finance_analysis.tasks.celery.cron import LocalizedCrontab, compute_next_run

# === Queues ===
# A single worker still listens to all of these; the split keeps routing
# explicit and ready for future per-queue scaling.
QUEUE_ALERTS = "alerts"  # A 股 / 美股盘中提醒
QUEUE_ANALYSIS = "analysis"  # 全量分析、盘前分析、收盘复盘
QUEUE_INGESTION = "ingestion"  # 新闻与财经日历
QUEUE_MAINTENANCE = "maintenance"  # 预留维护任务
QUEUE_DEFAULT = "celery"  # 默认任务

ALL_QUEUES = (
    QUEUE_ALERTS,
    QUEUE_ANALYSIS,
    QUEUE_INGESTION,
    QUEUE_MAINTENANCE,
    QUEUE_DEFAULT,
)

# === Timezones ===
SCHEDULE_TIMEZONE = "Asia/Shanghai"
US_TIMEZONE = "America/New_York"

# === Expiry windows (seconds) ===
# Expired intraday deliveries must not run tens of minutes late.
EXPIRES_INTRADAY = 10 * 60
EXPIRES_PREMARKET = 30 * 60
EXPIRES_NEWS = 30 * 60
EXPIRES_CALENDAR = 60 * 60
EXPIRES_POSTMARKET_REVIEW = 90 * 60
EXPIRES_DAILY = 6 * 60 * 60

# === Job identifiers (preserved from the previous APScheduler jobs) ===
JOB_DAILY_ANALYSIS = "analysis_daily"
JOB_MARKET_CALENDAR = "market_calendar"
JOB_US_PREMARKET_NEWS = "analysis_us_premarket_news"
JOB_US_PREMARKET_ANALYSIS = "analysis_us_premarket"
JOB_US_INTRADAY_ANALYSIS = "analysis_us_intraday"
JOB_US_POSTMARKET_REVIEW = "analysis_us_postmarket_review"
JOB_A_SHARE_INTRADAY_ANALYSIS = "analysis_a_share_intraday"


def celery_task_name(job_id: str) -> str:
    """Return the Celery task name bound to a scheduled ``job_id``."""
    return f"scheduled.{job_id}"


@dataclass(frozen=True)
class CronSchedule:
    """One cron window, bound to an explicit timezone."""

    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"
    timezone: str = SCHEDULE_TIMEZONE

    def to_crontab(self) -> crontab:
        """Build a timezone-aware Celery crontab for Beat scheduling."""
        return LocalizedCrontab(
            minute=self.minute,
            hour=self.hour,
            day_of_week=self.day_of_week,
            day_of_month=self.day_of_month,
            month_of_year=self.month_of_year,
            tz=self.timezone,
        )


@dataclass(frozen=True)
class ScheduledTaskDefinition:
    """Display metadata and scheduling rules for one periodic business task."""

    job_id: str
    name: str
    description: str
    task_type: str
    celery_task_name: str
    schedules: List[CronSchedule]
    schedule_text: str
    timezone: str
    queue: str
    expires: int
    enabled: bool = True
    allow_manual_run: bool = True

    def crontabs(self) -> List[crontab]:
        return [item.to_crontab() for item in self.schedules]

    def next_run_time(self, *, now: Optional[datetime] = None) -> Optional[datetime]:
        """Earliest next fire time across this definition's schedules (aware UTC)."""
        return compute_next_run(self.crontabs(), self.timezone, now=now)


_DEFINITIONS: List[ScheduledTaskDefinition] = [
    ScheduledTaskDefinition(
        job_id=JOB_DAILY_ANALYSIS,
        name="每日全量分析",
        description="分析自选股中的全部股票并生成汇总报告",
        task_type="scheduled_daily",
        celery_task_name=celery_task_name(JOB_DAILY_ANALYSIS),
        schedules=[CronSchedule(minute="0", hour="18", timezone=SCHEDULE_TIMEZONE)],
        schedule_text="每天 18:00",
        timezone=SCHEDULE_TIMEZONE,
        queue=QUEUE_ANALYSIS,
        expires=EXPIRES_DAILY,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_MARKET_CALENDAR,
        name="美股财经日历同步",
        description="同步未来美股财经事件并更新事件日历",
        task_type="scheduled_market_calendar",
        celery_task_name=celery_task_name(JOB_MARKET_CALENDAR),
        schedules=[CronSchedule(minute="0", hour="19", timezone=SCHEDULE_TIMEZONE)],
        schedule_text="每天 19:00",
        timezone=SCHEDULE_TIMEZONE,
        queue=QUEUE_INGESTION,
        expires=EXPIRES_CALENDAR,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_US_PREMARKET_NEWS,
        name="美股盘前新闻情报",
        description="抓取自选股和 Nasdaq-100 前 20 新闻并生成盘前情报",
        task_type="scheduled_us_premarket_news",
        celery_task_name=celery_task_name(JOB_US_PREMARKET_NEWS),
        schedules=[CronSchedule(minute="0", hour="20", timezone=SCHEDULE_TIMEZONE)],
        schedule_text="每天 20:00",
        timezone=SCHEDULE_TIMEZONE,
        queue=QUEUE_INGESTION,
        expires=EXPIRES_NEWS,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_US_PREMARKET_ANALYSIS,
        name="美股盘前分析",
        description="分析自选股中的美股并生成盘前报告",
        task_type="scheduled_us_premarket",
        celery_task_name=celery_task_name(JOB_US_PREMARKET_ANALYSIS),
        schedules=[CronSchedule(minute="0", hour="21", timezone=SCHEDULE_TIMEZONE)],
        schedule_text="每天 21:00",
        timezone=SCHEDULE_TIMEZONE,
        queue=QUEUE_ANALYSIS,
        expires=EXPIRES_PREMARKET,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_US_INTRADAY_ANALYSIS,
        name="美股盘中分析",
        description="检测自选美股盘中异动并按需提醒",
        task_type="scheduled_us_intraday",
        celery_task_name=celery_task_name(JOB_US_INTRADAY_ANALYSIS),
        schedules=[
            CronSchedule(minute="46,56", hour="9", day_of_week="mon-fri", timezone=US_TIMEZONE),
            CronSchedule(minute="6,16,26,36,46,56", hour="10-15", day_of_week="mon-fri", timezone=US_TIMEZONE),
        ],
        schedule_text="美股交易日 09:46-15:56 America/New_York，每10分钟",
        timezone=US_TIMEZONE,
        queue=QUEUE_ALERTS,
        expires=EXPIRES_INTRADAY,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_US_POSTMARKET_REVIEW,
        name="美股收盘复盘",
        description="美股收盘后分析指数、板块、自选股和市场新闻，生成每日复盘报告",
        task_type="scheduled_us_postmarket_review",
        celery_task_name=celery_task_name(JOB_US_POSTMARKET_REVIEW),
        schedules=[CronSchedule(minute="30", hour="16", timezone=US_TIMEZONE)],
        schedule_text="美股交易日 16:30 America/New_York",
        timezone=US_TIMEZONE,
        queue=QUEUE_ANALYSIS,
        expires=EXPIRES_POSTMARKET_REVIEW,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_A_SHARE_INTRADAY_ANALYSIS,
        name="A股盘中分析",
        description="分析A股市场情绪、板块轮动和自选股异动，识别涨停、炸板、强弱转换及风险信号",
        task_type="scheduled_a_share_intraday",
        celery_task_name=celery_task_name(JOB_A_SHARE_INTRADAY_ANALYSIS),
        schedules=[
            CronSchedule(
                minute="45,55",
                hour="9",
                day_of_week="mon-fri",
                timezone=SCHEDULE_TIMEZONE,
            ),
            CronSchedule(
                minute="5,15,25,35,45,55",
                hour="10",
                day_of_week="mon-fri",
                timezone=SCHEDULE_TIMEZONE,
            ),
            CronSchedule(
                minute="5,15,25",
                hour="11",
                day_of_week="mon-fri",
                timezone=SCHEDULE_TIMEZONE,
            ),
            CronSchedule(
                minute="0,10,20,30,40,50",
                hour="13-14",
                day_of_week="mon-fri",
                timezone=SCHEDULE_TIMEZONE,
            ),
            CronSchedule(
                minute="0",
                hour="15",
                day_of_week="mon-fri",
                timezone=SCHEDULE_TIMEZONE,
            ),
        ],
        schedule_text="A股交易日 09:45-11:25、13:00-15:00，每10分钟",
        timezone=SCHEDULE_TIMEZONE,
        queue=QUEUE_ALERTS,
        expires=EXPIRES_INTRADAY,
    ),
]

_DEFINITIONS_BY_JOB_ID: Dict[str, ScheduledTaskDefinition] = {item.job_id: item for item in _DEFINITIONS}
_DEFINITIONS_BY_TASK_NAME: Dict[str, ScheduledTaskDefinition] = {
    item.celery_task_name: item for item in _DEFINITIONS
}


def get_scheduled_task_definitions() -> List[ScheduledTaskDefinition]:
    """Return all code-defined scheduled task definitions."""
    return list(_DEFINITIONS)


def get_scheduled_task_definition(job_id: str) -> Optional[ScheduledTaskDefinition]:
    """Return one definition by ``job_id`` (or ``None``)."""
    return _DEFINITIONS_BY_JOB_ID.get(job_id)


def get_definition_by_task_name(task_name: str) -> Optional[ScheduledTaskDefinition]:
    """Return one definition by its Celery task name (or ``None``)."""
    return _DEFINITIONS_BY_TASK_NAME.get(task_name)


def build_beat_schedule() -> Dict[str, Dict[str, Any]]:
    """Build the Celery ``beat_schedule`` mapping from the registry.

    A definition with multiple cron windows yields one Beat entry per window so
    every window is delivered independently while sharing the same task,
    ``job_id`` payload, queue, and expiry.
    """
    schedule: Dict[str, Dict[str, Any]] = {}
    for definition in _DEFINITIONS:
        if not definition.enabled:
            continue
        crontabs = definition.crontabs()
        for index, cron in enumerate(crontabs):
            entry_key = definition.job_id if len(crontabs) == 1 else f"{definition.job_id}__{index}"
            schedule[entry_key] = {
                "task": definition.celery_task_name,
                "schedule": cron,
                "options": {
                    "queue": definition.queue,
                    "expires": definition.expires,
                },
                "kwargs": {
                    "scheduler_job_id": definition.job_id,
                    "_trigger_source": "scheduler",
                },
            }
    return schedule


def build_task_routes() -> Dict[str, Dict[str, str]]:
    """Build ``task_routes`` mapping each scheduled task name to its queue."""
    return {definition.celery_task_name: {"queue": definition.queue} for definition in _DEFINITIONS}


def get_task_queues() -> tuple[str, ...]:
    """Return every queue a worker must listen to."""
    return ALL_QUEUES


__all__ = [
    "ALL_QUEUES",
    "CronSchedule",
    "ScheduledTaskDefinition",
    "SCHEDULE_TIMEZONE",
    "US_TIMEZONE",
    "build_beat_schedule",
    "build_task_routes",
    "celery_task_name",
    "get_definition_by_task_name",
    "get_scheduled_task_definition",
    "get_scheduled_task_definitions",
    "get_task_queues",
]

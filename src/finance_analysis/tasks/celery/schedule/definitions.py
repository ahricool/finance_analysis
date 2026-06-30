# -*- coding: utf-8 -*-
"""Structured definitions for all code-defined periodic tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from celery.schedules import crontab

from .constants import (
    EXPIRES_CALENDAR,
    EXPIRES_DAILY,
    EXPIRES_INTRADAY,
    EXPIRES_NEWS,
    EXPIRES_POSTMARKET_REVIEW,
    EXPIRES_PREMARKET,
    EXPIRES_SIGNAL_EVALUATION,
    JOB_A_SHARE_INTRADAY_ANALYSIS,
    JOB_DAILY_ANALYSIS,
    JOB_MARKET_CALENDAR,
    JOB_SIGNAL_EVALUATION_CN,
    JOB_SIGNAL_EVALUATION_US,
    JOB_US_INTRADAY_ANALYSIS,
    JOB_US_POSTMARKET_REVIEW,
    JOB_US_PREMARKET_ANALYSIS,
    JOB_US_PREMARKET_NEWS,
    QUEUE_ALERTS,
    QUEUE_ANALYSIS,
    QUEUE_INGESTION,
    SCHEDULE_TIMEZONE,
    US_TIMEZONE,
    celery_task_name,
)
from .cron import LocalizedCrontab, compute_next_run


@dataclass(frozen=True)
class CronSchedule:
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"
    timezone: str = SCHEDULE_TIMEZONE

    def to_crontab(self) -> crontab:
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
    job_id: str
    name: str
    description: str
    task_type: str
    celery_task_name: str
    schedules: tuple[CronSchedule, ...]
    schedule_text: str
    timezone: str
    queue: str
    expires: int
    enabled: bool = True
    allow_manual_run: bool = True

    def crontabs(self) -> list[crontab]:
        return [item.to_crontab() for item in self.schedules]

    def next_run_time(self, *, now: Optional[datetime] = None) -> Optional[datetime]:
        return compute_next_run(self.crontabs(), self.timezone, now=now)


SCHEDULED_TASK_DEFINITIONS = (
    ScheduledTaskDefinition(
        job_id=JOB_DAILY_ANALYSIS,
        name="每日全量分析",
        description="分析自选股中的全部股票并生成汇总报告",
        task_type="scheduled_daily",
        celery_task_name=celery_task_name(JOB_DAILY_ANALYSIS),
        schedules=(CronSchedule(minute="0", hour="18"),),
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
        schedules=(CronSchedule(minute="0", hour="19"),),
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
        schedules=(CronSchedule(minute="0", hour="20"),),
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
        schedules=(CronSchedule(minute="0", hour="21"),),
        schedule_text="每天 21:00",
        timezone=SCHEDULE_TIMEZONE,
        queue=QUEUE_ANALYSIS,
        expires=EXPIRES_PREMARKET,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_US_INTRADAY_ANALYSIS,
        name="美股盘中分析",
        description="每5分钟使用实时行情检测自选美股、QQQ及板块异动，按信号状态变化提醒",
        task_type="scheduled_us_intraday",
        celery_task_name=celery_task_name(JOB_US_INTRADAY_ANALYSIS),
        schedules=(
            CronSchedule(minute="45,50,55", hour="9", day_of_week="mon-fri", timezone=US_TIMEZONE),
            CronSchedule(minute="*/5", hour="10-15", day_of_week="mon-fri", timezone=US_TIMEZONE),
        ),
        schedule_text="美股交易日 09:45-15:55 America/New_York，每5分钟",
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
        schedules=(CronSchedule(minute="30", hour="16", timezone=US_TIMEZONE),),
        schedule_text="美股交易日 16:30 America/New_York",
        timezone=US_TIMEZONE,
        queue=QUEUE_ANALYSIS,
        expires=EXPIRES_POSTMARKET_REVIEW,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_A_SHARE_INTRADAY_ANALYSIS,
        name="A股盘中分析",
        description="每5分钟初筛A股全市场并精析有限候选，按信号状态变化提醒",
        task_type="scheduled_a_share_intraday",
        celery_task_name=celery_task_name(JOB_A_SHARE_INTRADAY_ANALYSIS),
        schedules=(
            CronSchedule(minute="45,50,55", hour="9", day_of_week="mon-fri"),
            CronSchedule(minute="*/5", hour="10", day_of_week="mon-fri"),
            CronSchedule(minute="0,5,10,15,20,25,30", hour="11", day_of_week="mon-fri"),
            CronSchedule(minute="*/5", hour="13-14", day_of_week="mon-fri"),
            CronSchedule(minute="0", hour="15", day_of_week="mon-fri"),
        ),
        schedule_text="A股交易日 09:45-11:30、13:00-15:00，每5分钟（午休不运行）",
        timezone=SCHEDULE_TIMEZONE,
        queue=QUEUE_ALERTS,
        expires=EXPIRES_INTRADAY,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_SIGNAL_EVALUATION_CN,
        name="A股信号评价",
        description="仅补充最近15个自然日A股信号缺失且已成熟的评价周期",
        task_type="scheduled_signal_evaluation_cn",
        celery_task_name=celery_task_name(JOB_SIGNAL_EVALUATION_CN),
        schedules=(CronSchedule(minute="30", hour="18", day_of_week="mon-fri"),),
        schedule_text="周一至周五 18:30 Asia/Shanghai",
        timezone=SCHEDULE_TIMEZONE,
        queue=QUEUE_ANALYSIS,
        expires=EXPIRES_SIGNAL_EVALUATION,
    ),
    ScheduledTaskDefinition(
        job_id=JOB_SIGNAL_EVALUATION_US,
        name="美股信号评价",
        description="仅补充最近15个自然日美股信号缺失且已成熟的评价周期",
        task_type="scheduled_signal_evaluation_us",
        celery_task_name=celery_task_name(JOB_SIGNAL_EVALUATION_US),
        schedules=(
            CronSchedule(
                minute="0",
                hour="17",
                day_of_week="mon-fri",
                timezone=US_TIMEZONE,
            ),
        ),
        schedule_text="周一至周五 17:00 America/New_York",
        timezone=US_TIMEZONE,
        queue=QUEUE_ANALYSIS,
        expires=EXPIRES_SIGNAL_EVALUATION,
    ),
)

__all__ = ["CronSchedule", "SCHEDULED_TASK_DEFINITIONS", "ScheduledTaskDefinition"]

# -*- coding: utf-8 -*-
"""
===================================
定时调度模块（APScheduler）
===================================

将定时任务**写死在代码中**，不再从环境变量或外部配置读取调度参数：

- 每日 :data:`DAILY_SCHEDULE_HOUR` : :data:`DAILY_SCHEDULE_MINUTE` 执行一次全量分析。
- 北京时间 21:00 执行美股盘前分析，仅分析自选股中标记为美股的股票。
- 每 15 分钟分别触发一次美股盘中分析和 A股盘中分析（当前为空流程占位）。
- 进程启动时如 :data:`RUN_IMMEDIATELY_ON_STARTUP` 为 ``True``，会立即执行一次。

如需修改调度策略，请直接修改本文件中的常量或 ``_daily_analysis_task``，
然后重启进程。

由 ``api.app`` 的 FastAPI lifespan 负责 ``start``/``shutdown``。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# === 调度参数（修改后需重启进程）===
DAILY_SCHEDULE_HOUR = 18
DAILY_SCHEDULE_MINUTE = 0
US_PREMARKET_SCHEDULE_HOUR = 21
US_PREMARKET_SCHEDULE_MINUTE = 0
INTRADAY_ANALYSIS_INTERVAL_MINUTES = 15
SCHEDULE_TIMEZONE = "Asia/Shanghai"
RUN_IMMEDIATELY_ON_STARTUP = True

_JOB_DAILY_ANALYSIS = "analysis_daily"
_JOB_US_PREMARKET_ANALYSIS = "analysis_us_premarket"
_JOB_US_INTRADAY_ANALYSIS = "analysis_us_intraday"
_JOB_CN_INTRADAY_ANALYSIS = "analysis_cn_intraday"


def _daily_analysis_task() -> None:
    """每日定时任务：执行一次完整的股票分析流水线。"""
    logger.info("=" * 50)
    logger.info("定时任务开始执行 - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 50)
    try:
        from src.config import get_config
        from src.core.pipeline import StockAnalysisPipeline

        pipeline = StockAnalysisPipeline(config=get_config())
        pipeline.run()
    except Exception as exc:
        logger.exception("定时任务执行失败: %s", exc)
    else:
        logger.info(
            "定时任务执行完成 - %s",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


def _us_premarket_analysis_task() -> None:
    """美股盘前定时任务：仅分析自选股中标记为美股的股票。"""
    logger.info("=" * 50)
    logger.info("美股盘前分析任务开始执行 - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 50)
    try:
        from src.config import get_config
        from src.core.pipeline import StockAnalysisPipeline
        from src.repositories.watch_list_repo import get_watch_list_codes_by_market

        stock_codes = get_watch_list_codes_by_market("US")
        if not stock_codes:
            logger.warning("未配置美股自选股，跳过美股盘前分析任务")
            return

        pipeline = StockAnalysisPipeline(config=get_config())
        pipeline.run(stock_codes=stock_codes)
    except Exception as exc:
        logger.exception("美股盘前分析任务执行失败: %s", exc)
    else:
        logger.info(
            "美股盘前分析任务执行完成 - %s",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


def _us_intraday_analysis_task() -> None:
    """美股盘中分析任务占位：当前流程为空。"""
    logger.info("美股盘中分析任务触发 - %s（当前为空流程）", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def _cn_intraday_analysis_task() -> None:
    """A股盘中分析任务占位：当前流程为空。"""
    logger.info("A股盘中分析任务触发 - %s（当前为空流程）", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def start_embedded_analysis_scheduler():
    """启动 APScheduler，注册每日分析 Cron 任务。

    返回 ``BackgroundScheduler`` 实例；调用方需在停机时调用
    :func:`shutdown_embedded_analysis_scheduler` 释放线程。
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError as exc:  # pragma: no cover - import guard
        logger.error("apscheduler 未安装，请执行: pip install apscheduler")
        raise ImportError("请安装 apscheduler 库: pip install apscheduler") from exc

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _daily_analysis_task,
        CronTrigger(hour=DAILY_SCHEDULE_HOUR, minute=DAILY_SCHEDULE_MINUTE, timezone=SCHEDULE_TIMEZONE),
        id=_JOB_DAILY_ANALYSIS,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _us_premarket_analysis_task,
        CronTrigger(
            hour=US_PREMARKET_SCHEDULE_HOUR,
            minute=US_PREMARKET_SCHEDULE_MINUTE,
            timezone=SCHEDULE_TIMEZONE,
        ),
        id=_JOB_US_PREMARKET_ANALYSIS,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _us_intraday_analysis_task,
        IntervalTrigger(minutes=INTRADAY_ANALYSIS_INTERVAL_MINUTES, timezone=SCHEDULE_TIMEZONE),
        id=_JOB_US_INTRADAY_ANALYSIS,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _cn_intraday_analysis_task,
        IntervalTrigger(minutes=INTRADAY_ANALYSIS_INTERVAL_MINUTES, timezone=SCHEDULE_TIMEZONE),
        id=_JOB_CN_INTRADAY_ANALYSIS,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "APScheduler 已启动，每日定时任务: %02d:%02d，美股盘前分析: %02d:%02d，盘中分析间隔: %d 分钟 (%s)",
        DAILY_SCHEDULE_HOUR,
        DAILY_SCHEDULE_MINUTE,
        US_PREMARKET_SCHEDULE_HOUR,
        US_PREMARKET_SCHEDULE_MINUTE,
        INTRADAY_ANALYSIS_INTERVAL_MINUTES,
        SCHEDULE_TIMEZONE,
    )
    job = scheduler.get_job(_JOB_DAILY_ANALYSIS)
    if job is not None and job.next_run_time is not None:
        logger.info("下次执行时间: %s", job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))

    if RUN_IMMEDIATELY_ON_STARTUP:
        logger.info("启动时立即执行一次定时任务...")
        _daily_analysis_task()

    return scheduler


def shutdown_embedded_analysis_scheduler(scheduler) -> None:
    """停机时调用：等待运行中的任务完成后停止调度器。"""
    if scheduler is None:
        return
    try:
        scheduler.shutdown(wait=True)
    finally:
        logger.info("APScheduler 已停止")

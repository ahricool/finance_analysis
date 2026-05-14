# -*- coding: utf-8 -*-
"""
===================================
定时调度模块（APScheduler）
===================================

职责：
1. 支持每日定时执行股票分析
2. 支持定时后台任务（如 Event Monitor）
3. 与 FastAPI 生命周期集成；也可在无 Web 服务时独立阻塞运行

依赖：
- APScheduler: 定时任务调度
"""

from __future__ import annotations

import logging
import re
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_JOB_DAILY_ANALYSIS = "analysis_daily"
_JOB_SCHEDULE_SYNC = "analysis_schedule_time_sync"
_JOB_PREFIX_BG = "analysis_bg_"

_pending_analysis_schedule_spec: Optional["AnalysisScheduleSpec"] = None
_pending_lock = threading.Lock()


@dataclass
class AnalysisScheduleSpec:
    """Parameters for the built-in daily analysis scheduler."""

    task: Callable[[], None]
    schedule_time: str
    run_immediately: bool = True
    background_tasks: Optional[List[Dict[str, Any]]] = None
    schedule_time_provider: Optional[Callable[[], str]] = None


def register_pending_analysis_schedule(spec: AnalysisScheduleSpec) -> None:
    """Register schedule spec to be picked up by FastAPI lifespan (must run before uvicorn starts)."""
    global _pending_analysis_schedule_spec
    with _pending_lock:
        _pending_analysis_schedule_spec = spec


def pop_pending_analysis_schedule() -> Optional[AnalysisScheduleSpec]:
    """Atomically take pending spec for embedded startup; returns None if nothing registered."""
    global _pending_analysis_schedule_spec
    with _pending_lock:
        spec = _pending_analysis_schedule_spec
        _pending_analysis_schedule_spec = None
        return spec


class GracefulShutdown:
    """捕获 SIGTERM/SIGINT，供独立阻塞模式退出。"""

    def __init__(self) -> None:
        self.shutdown_requested = False
        self._lock = threading.Lock()
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame) -> None:
        with self._lock:
            if not self.shutdown_requested:
                logger.info("收到退出信号 (%s)，正在停止调度器...", signum)
                self.shutdown_requested = True

    @property
    def should_shutdown(self) -> bool:
        with self._lock:
            return self.shutdown_requested


def _is_valid_schedule_time(schedule_time: str) -> bool:
    candidate = (schedule_time or "").strip()
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", candidate))


def _parse_hh_mm(schedule_time: str) -> tuple[int, int]:
    parts = (schedule_time or "").strip().split(":")
    return int(parts[0]), int(parts[1])


class AnalysisSchedulerBundle:
    """
    使用 APScheduler BackgroundScheduler 托管每日分析与可选周期任务。
    """

    def __init__(self, spec: AnalysisScheduleSpec) -> None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError as exc:  # pragma: no cover - import guard
            logger.error("apscheduler 未安装，请执行: pip install apscheduler")
            raise ImportError("请安装 apscheduler 库: pip install apscheduler") from exc

        self._spec = spec
        self.schedule_time = (spec.schedule_time or "").strip() or "18:00"
        if not _is_valid_schedule_time(self.schedule_time):
            raise ValueError(f"无效的定时执行时间: {spec.schedule_time!r}")

        self._scheduler = BackgroundScheduler()
        self._schedule_time_provider = spec.schedule_time_provider
        self._started = False

    def _safe_run_task(self) -> None:
        if self._spec.task is None:
            return
        try:
            logger.info("=" * 50)
            logger.info("定时任务开始执行 - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            logger.info("=" * 50)
            self._spec.task()
            logger.info("定时任务执行完成 - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as exc:
            logger.exception("定时任务执行失败: %s", exc)

    def _safe_background(self, fn: Callable[[], None], name: str) -> None:
        try:
            logger.info("后台任务开始执行: %s", name)
            fn()
        except Exception as exc:
            logger.exception("后台任务执行失败 [%s]: %s", name, exc)

    def _refresh_daily_schedule_if_needed(self) -> None:
        if self._schedule_time_provider is None:
            return
        try:
            latest = (self._schedule_time_provider() or "").strip()
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.warning("读取最新 SCHEDULE_TIME 失败，继续沿用 %s: %s", self.schedule_time, exc)
            return

        if not latest or latest == self.schedule_time:
            return

        if not _is_valid_schedule_time(latest):
            logger.warning("检测到无效的定时执行时间 %r，继续沿用 %s", latest, self.schedule_time)
            return

        self._apply_daily_cron(latest, log_reschedule=True)

    def _apply_daily_cron(self, hh_mm: str, *, log_reschedule: bool = False) -> None:
        from apscheduler.triggers.cron import CronTrigger

        hour, minute = _parse_hh_mm(hh_mm)
        previous = self.schedule_time
        self.schedule_time = hh_mm.strip()

        trigger = CronTrigger(hour=hour, minute=minute)
        if self._scheduler.get_job(_JOB_DAILY_ANALYSIS):
            self._scheduler.reschedule_job(_JOB_DAILY_ANALYSIS, trigger=trigger)
        else:
            self._scheduler.add_job(
                self._safe_run_task,
                trigger,
                id=_JOB_DAILY_ANALYSIS,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        if log_reschedule and previous != self.schedule_time:
            logger.info(
                "检测到 SCHEDULE_TIME 变更，已将每日定时任务从 %s 更新为 %s",
                previous,
                self.schedule_time,
            )
        elif not log_reschedule:
            logger.info("已设置每日定时任务，执行时间: %s", self.schedule_time)

        next_run = self._next_daily_run_display()
        if next_run:
            logger.info("更新后的下次执行时间: %s", next_run)

    def _next_daily_run_display(self) -> str:
        job = self._scheduler.get_job(_JOB_DAILY_ANALYSIS)
        if job is None or job.next_run_time is None:
            return ""
        return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")

    def start(self) -> None:
        if self._started:
            return

        from apscheduler.triggers.interval import IntervalTrigger

        if self._spec.run_immediately:
            logger.info("立即执行一次任务...")
            self._safe_run_task()

        self._apply_daily_cron(self.schedule_time, log_reschedule=False)

        if self._schedule_time_provider is not None:
            self._scheduler.add_job(
                self._refresh_daily_schedule_if_needed,
                IntervalTrigger(seconds=30),
                id=_JOB_SCHEDULE_SYNC,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        for entry in self._spec.background_tasks or []:
            name = entry.get("name") or getattr(entry["task"], "__name__", "background_task")
            interval_seconds = max(1, int(entry["interval_seconds"]))
            run_immediately = bool(entry.get("run_immediately", False))
            task_fn = entry["task"]
            job_id = f"{_JOB_PREFIX_BG}{name}"

            now = datetime.now()
            next_at = now if run_immediately else now + timedelta(seconds=interval_seconds)
            self._scheduler.add_job(
                self._safe_background,
                IntervalTrigger(seconds=interval_seconds),
                args=[task_fn, name],
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                next_run_time=next_at,
            )
            logger.info(
                "已注册后台任务: %s（间隔 %s 秒，立即执行=%s）",
                name,
                interval_seconds,
                run_immediately,
            )

        self._scheduler.start()
        self._started = True
        logger.info("APScheduler 已启动，下次执行时间: %s", self._next_daily_run_display() or "未设置")

    def shutdown(self) -> None:
        if not self._started:
            return
        try:
            self._scheduler.shutdown(wait=True)
        finally:
            self._started = False
            logger.info("APScheduler 已停止")


def run_standalone_analysis_scheduler(spec: AnalysisScheduleSpec) -> None:
    """无 FastAPI 时阻塞运行，直到收到 SIGINT/SIGTERM。"""
    shutdown = GracefulShutdown()
    bundle = AnalysisSchedulerBundle(spec)
    bundle.start()
    try:
        while not shutdown.should_shutdown:
            time.sleep(1)
    finally:
        bundle.shutdown()


def run_with_schedule(
    task: Callable[[], None],
    schedule_time: str = "18:00",
    run_immediately: bool = True,
    background_tasks: Optional[List[Dict[str, Any]]] = None,
    schedule_time_provider: Optional[Callable[[], str]] = None,
) -> None:
    """
    便捷函数：独立进程定时模式（不使用 FastAPI 嵌入调度时）。

    当 ``main.py`` 与 FastAPI 同进程启动时，应使用 ``register_pending_analysis_schedule``
    + FastAPI lifespan，而非本函数。
    """
    spec = AnalysisScheduleSpec(
        task=task,
        schedule_time=schedule_time,
        run_immediately=run_immediately,
        background_tasks=background_tasks,
        schedule_time_provider=schedule_time_provider,
    )
    run_standalone_analysis_scheduler(spec)


def attach_embedded_analysis_scheduler_from_pending() -> Optional[AnalysisSchedulerBundle]:
    """由 FastAPI lifespan 调用：如有待处理 spec 则启动并返回 bundle。"""
    spec = pop_pending_analysis_schedule()
    if spec is None:
        return None
    bundle = AnalysisSchedulerBundle(spec)
    bundle.start()
    return bundle


def shutdown_embedded_analysis_scheduler(bundle: Optional[AnalysisSchedulerBundle]) -> None:
    if bundle is not None:
        bundle.shutdown()


if __name__ == "__main__":  # pragma: no cover - manual smoke
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    )

    def test_task() -> None:
        print(f"任务执行中... {datetime.now()}")
        time.sleep(1)
        print("任务完成!")

    print("启动测试调度器（按 Ctrl+C 退出）")
    run_with_schedule(test_task, schedule_time="23:59", run_immediately=True)

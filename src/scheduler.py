# -*- coding: utf-8 -*-
"""
===================================
定时调度模块（APScheduler）
===================================

职责：
1. 支持每日定时执行股票分析
2. 支持定时后台任务（如 Event Monitor）
3. 与 FastAPI 生命周期集成（由 ``api.app`` 的 lifespan 启动/停止）

依赖：
- APScheduler: 定时任务调度
"""

from __future__ import annotations

import logging
import re
import threading
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


def try_build_analysis_schedule_spec_from_config() -> Optional[AnalysisScheduleSpec]:
    """
    当未通过外部 ``register_pending_analysis_schedule`` 注册 pending spec 时，
    若 ``SCHEDULE_ENABLED=true``，从当前配置构建 ``AnalysisScheduleSpec``。
    """
    from src.config import get_config

    config = get_config()
    if not getattr(config, "schedule_enabled", False):
        return None

    import main as main_mod

    logger.info(
        "SCHEDULE_ENABLED=true：在 FastAPI 进程内自动启动定时分析（无需 --schedule）",
    )
    args = main_mod.build_embedded_schedule_args()
    scheduled_stock_codes = main_mod._resolve_scheduled_stock_codes(None)
    schedule_time_provider = main_mod._build_schedule_time_provider(config.schedule_time)
    should_run_immediately = getattr(config, "schedule_run_immediately", True)

    def scheduled_task() -> None:
        runtime_config = main_mod._reload_runtime_config()
        main_mod.run_full_analysis(runtime_config, args, scheduled_stock_codes)

    background_tasks: List[Dict[str, Any]] = []
    if getattr(config, "agent_event_monitor_enabled", False):
        from src.agent.events import build_event_monitor_from_config, run_event_monitor_once

        monitor = build_event_monitor_from_config(config)
        if monitor is not None:
            interval_minutes = max(1, getattr(config, "agent_event_monitor_interval_minutes", 5))

            def event_monitor_task() -> None:
                triggered = run_event_monitor_once(monitor)
                if triggered:
                    logger.info("[EventMonitor] 本轮触发 %d 条提醒", len(triggered))

            background_tasks.append(
                {
                    "task": event_monitor_task,
                    "interval_seconds": interval_minutes * 60,
                    "run_immediately": True,
                    "name": "agent_event_monitor",
                }
            )
        else:
            logger.info("EventMonitor 已启用，但未加载到有效规则，跳过后台提醒任务")

    return AnalysisScheduleSpec(
        task=scheduled_task,
        schedule_time=config.schedule_time,
        run_immediately=should_run_immediately,
        background_tasks=background_tasks or None,
        schedule_time_provider=schedule_time_provider,
    )


def start_embedded_analysis_scheduler() -> Optional[AnalysisSchedulerBundle]:
    """
    FastAPI lifespan 入口：优先消费外部注册的 pending spec；
    若无且 ``SCHEDULE_ENABLED=true``，则按配置自动构建并启动。
    """
    spec = pop_pending_analysis_schedule()
    if spec is None:
        spec = try_build_analysis_schedule_spec_from_config()
    if spec is None:
        return None
    bundle = AnalysisSchedulerBundle(spec)
    bundle.start()
    return bundle


def shutdown_embedded_analysis_scheduler(bundle: Optional[AnalysisSchedulerBundle]) -> None:
    if bundle is not None:
        bundle.shutdown()

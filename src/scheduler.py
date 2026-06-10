# -*- coding: utf-8 -*-
"""
===================================
定时调度模块（APScheduler）
===================================

将定时任务**写死在代码中**，不再从环境变量或外部配置读取调度参数：

- 每日 :data:`DAILY_SCHEDULE_HOUR` : :data:`DAILY_SCHEDULE_MINUTE` 执行一次全量分析。
- 北京时间 21:00 执行美股盘前分析，仅分析自选股中标记为美股的股票。
- 每 15 分钟执行一次美股盘中分析（当前任务流程为空）。
- 每 15 分钟执行一次 A 股盘中分析（当前任务流程为空）。
- 进程启动时如 :data:`RUN_IMMEDIATELY_ON_STARTUP` 为 ``True``，会立即执行一次。

如需修改调度策略，请直接修改本文件中的常量或 ``_daily_analysis_task``，
然后重启进程。

由 ``api.app`` 的 FastAPI lifespan 负责 ``start``/``shutdown``。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional, Sequence
from zoneinfo import ZoneInfo

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
_JOB_A_SHARE_INTRADAY_ANALYSIS = "analysis_a_share_intraday"


def _scheduled_now() -> datetime:
    """Return scheduler-local current time for calendar grouping."""
    return datetime.now(ZoneInfo(SCHEDULE_TIMEZONE))


def _resolve_report_type(config: Any):
    """Resolve configured report type using the same mapping as the pipeline."""
    from src.enums import ReportType

    report_type_str = str(getattr(config, "report_type", "simple") or "simple").lower()
    if report_type_str == "brief":
        return ReportType.BRIEF
    if report_type_str == "full":
        return ReportType.FULL
    return ReportType.SIMPLE


def _result_summary_lines(results: Sequence[Any]) -> List[str]:
    """Build compact markdown summary lines for successful analysis results."""
    lines: List[str] = []
    for result in results[:20]:
        code = str(getattr(result, "code", "") or "-")
        name = str(getattr(result, "name", "") or code)
        score = getattr(result, "sentiment_score", None)
        advice = str(getattr(result, "operation_advice", "") or "-")
        trend = str(getattr(result, "trend_prediction", "") or "-")
        confidence = str(getattr(result, "confidence_level", "") or "-")
        score_text = "-" if score is None else str(score)
        lines.append(f"- **{name}({code})**：评分 {score_text}，{trend}，建议 {advice}，置信度 {confidence}")
    if len(results) > 20:
        lines.append(f"- ……另有 {len(results) - 20} 条结果，请查看下方完整报告。")
    return lines


def _build_calendar_content(
    *,
    task_name: str,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    total_count: int,
    results: Sequence[Any],
    report: Optional[str] = None,
    error: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    """Render scheduled task execution details as markdown for the calendar."""
    elapsed = (finished_at - started_at).total_seconds()
    success_count = len(results)
    failed_count = max(total_count - success_count, 0)
    lines = [
        f"## {task_name}",
        "",
        f"- 执行状态：{status}",
        f"- 开始时间：{started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 结束时间：{finished_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 耗时：{elapsed:.2f} 秒",
        f"- 计划分析数量：{total_count}",
        f"- 成功数量：{success_count}",
        f"- 失败/未产出数量：{failed_count}",
    ]
    if note:
        lines.extend(["", f"> {note}"])
    if error:
        lines.extend(["", "### 错误信息", "", f"```text\n{error}\n```"])
    if results:
        lines.extend(["", "### 执行结果", "", *_result_summary_lines(results)])
    if report:
        lines.extend(["", "### 报告", "", report])
    return "\n".join(lines).strip()


def _record_scheduled_task_result(
    *,
    task_name: str,
    type: str,
    started_at: datetime,
    finished_at: datetime,
    total_count: int,
    results: Sequence[Any],
    report: Optional[str] = None,
    error: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    """Create a calendar record for a completed scheduled task run."""
    from src.repositories.calendar_repo import CalendarRepo
    from src.repositories.user_repo import UserRepository

    status = "失败" if error else ("跳过" if total_count == 0 else "完成")
    title = f"{task_name}{status}：成功 {len(results)} / 总计 {total_count}"
    content = _build_calendar_content(
        task_name=task_name,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        total_count=total_count,
        results=results,
        report=report,
        error=error,
        note=note,
    )
    uid = UserRepository().ensure_default_admin()
    CalendarRepo().create(
        uid=uid,
        time=finished_at,
        title=title[:120],
        content=content,
        type=type,
    )


def _safe_record_scheduled_task_result(**kwargs: Any) -> None:
    """Best-effort calendar recording; never fail the scheduler because of UI history."""
    try:
        _record_scheduled_task_result(**kwargs)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("写入定时任务日历记录失败: %s", exc, exc_info=True)


def _daily_analysis_task() -> None:
    """每日定时任务：执行一次完整的股票分析流水线。"""
    task_name = "每日全量分析"
    started_at = _scheduled_now()
    logger.info("=" * 50)
    logger.info("定时任务开始执行 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 50)
    results: List[Any] = []
    total_count = 0
    report: Optional[str] = None
    try:
        from src.config import get_config
        from src.core.pipeline import StockAnalysisPipeline
        from src.repositories.watch_list_repo import get_watch_list_codes

        config = get_config()
        stock_codes = get_watch_list_codes()
        total_count = len(stock_codes)
        pipeline = StockAnalysisPipeline(config=config)
        results = pipeline.run(stock_codes=stock_codes)
        if results:
            report = pipeline._generate_aggregate_report(results, _resolve_report_type(config))
    except Exception as exc:
        finished_at = _scheduled_now()
        logger.exception("定时任务执行失败: %s", exc)
        _safe_record_scheduled_task_result(
            task_name=task_name,
            type="scheduled_daily",
            started_at=started_at,
            finished_at=finished_at,
            total_count=total_count,
            results=results,
            report=report,
            error=str(exc),
        )
    else:
        finished_at = _scheduled_now()
        _safe_record_scheduled_task_result(
            task_name=task_name,
            type="scheduled_daily",
            started_at=started_at,
            finished_at=finished_at,
            total_count=total_count,
            results=results,
            report=report,
            note="本记录由定时任务自动写入，可展开查看执行结果与报告。",
        )
        logger.info(
            "定时任务执行完成 - %s",
            finished_at.strftime("%Y-%m-%d %H:%M:%S"),
        )


def _us_premarket_analysis_task() -> None:
    """美股盘前定时任务：仅分析自选股中标记为美股的股票。"""
    task_name = "美股盘前分析"
    started_at = _scheduled_now()
    logger.info("=" * 50)
    logger.info("美股盘前分析任务开始执行 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 50)
    results: List[Any] = []
    total_count = 0
    report: Optional[str] = None
    try:
        from src.config import get_config
        from src.core.pipeline import StockAnalysisPipeline
        from src.repositories.watch_list_repo import get_watch_list_codes_by_market

        stock_codes = get_watch_list_codes_by_market("US")
        total_count = len(stock_codes)
        if not stock_codes:
            logger.warning("未配置美股自选股，跳过美股盘前分析任务")
            finished_at = _scheduled_now()
            _safe_record_scheduled_task_result(
                task_name=task_name,
                type="scheduled_us_premarket",
                started_at=started_at,
                finished_at=finished_at,
                total_count=0,
                results=[],
                note="未配置美股自选股，本次定时任务已跳过。",
            )
            return

        config = get_config()
        pipeline = StockAnalysisPipeline(config=config)
        results = pipeline.run(stock_codes=stock_codes)
        if results:
            report = pipeline._generate_aggregate_report(results, _resolve_report_type(config))
    except Exception as exc:
        finished_at = _scheduled_now()
        logger.exception("美股盘前分析任务执行失败: %s", exc)
        _safe_record_scheduled_task_result(
            task_name=task_name,
            type="scheduled_us_premarket",
            started_at=started_at,
            finished_at=finished_at,
            total_count=total_count,
            results=results,
            report=report,
            error=str(exc),
        )
    else:
        finished_at = _scheduled_now()
        _safe_record_scheduled_task_result(
            task_name=task_name,
            type="scheduled_us_premarket",
            started_at=started_at,
            finished_at=finished_at,
            total_count=total_count,
            results=results,
            report=report,
            note="本记录由定时任务自动写入，可展开查看执行结果与报告。",
        )
        logger.info(
            "美股盘前分析任务执行完成 - %s",
            finished_at.strftime("%Y-%m-%d %H:%M:%S"),
        )


def _us_intraday_analysis_task() -> None:
    """美股盘中定时任务：检测自选美股的盘中异动并按需提醒。"""
    started_at = _scheduled_now()
    logger.info("美股盘中分析任务触发 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        from src.config import get_config
        from src.repositories.watch_list_repo import get_watch_list_codes_by_market
        from src.services.us_intraday_analysis_service import USIntradayAnalysisService

        stock_codes = get_watch_list_codes_by_market("US")
        if not stock_codes:
            logger.info("未配置美股自选股，跳过美股盘中分析任务")
            return

        service = USIntradayAnalysisService(config=get_config())
        summary = service.run(stock_codes)
        if not summary.market_open:
            logger.info("当前不是美股盘中交易时段，跳过美股盘中分析任务")
            return

        logger.info(
            "美股盘中分析完成: total=%s processed=%s skipped=%s candidates=%s signals=%s errors=%s",
            summary.total_symbols,
            summary.processed_symbols,
            summary.skipped_symbols,
            summary.candidate_count,
            len(summary.signal_results),
            len(summary.errors),
        )
    except Exception as exc:
        logger.exception("美股盘中分析任务执行失败: %s", exc)


def _a_share_intraday_analysis_task() -> None:
    """A 股盘中定时任务：任务流程暂为空。"""
    logger.info(
        "A股盘中分析任务触发 - %s（任务流程暂为空）",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def start_embedded_analysis_scheduler():
    """启动 APScheduler，注册每日分析 Cron 任务。

    返回 ``BackgroundScheduler`` 实例；调用方需在停机时调用
    :func:`shutdown_embedded_analysis_scheduler` 释放线程。
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
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
        CronTrigger(minute=f"*/{INTRADAY_ANALYSIS_INTERVAL_MINUTES}", timezone=SCHEDULE_TIMEZONE),
        id=_JOB_US_INTRADAY_ANALYSIS,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _a_share_intraday_analysis_task,
        CronTrigger(minute=f"*/{INTRADAY_ANALYSIS_INTERVAL_MINUTES}", timezone=SCHEDULE_TIMEZONE),
        id=_JOB_A_SHARE_INTRADAY_ANALYSIS,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "APScheduler 已启动，每日定时任务: %02d:%02d，美股盘前分析: %02d:%02d，"
        "美股盘中分析/A股盘中分析: 每 %d 分钟一次 (%s)",
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

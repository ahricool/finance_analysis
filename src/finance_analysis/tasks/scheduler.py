# -*- coding: utf-8 -*-
"""
===================================
定时调度模块（APScheduler）
===================================

将定时任务**写死在代码中**，不再从环境变量或外部配置读取调度参数：

- 每日 :data:`DAILY_SCHEDULE_HOUR` : :data:`DAILY_SCHEDULE_MINUTE` 执行一次全量分析。
- 北京时间 20:00 执行美股盘前新闻情报，拉取关注股票和 Nasdaq-100 前 20 新闻。
- 北京时间 19:00 执行美股财经日历同步。
- 北京时间 21:00 执行美股盘前分析，仅分析自选股中标记为美股的股票。
- 每 15 分钟执行一次美股盘中分析（当前任务流程为空）。
- 每 15 分钟执行一次 A 股盘中分析（当前任务流程为空）。

如需修改调度策略，请直接修改本文件中的常量或 ``_daily_analysis_task``，
然后重启进程。

由 ``api.app`` 的 FastAPI lifespan 负责 ``start``/``shutdown``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional, Sequence, TypeVar
from zoneinfo import ZoneInfo

from finance_analysis.tasks.lifecycle import TaskSkipped, track_task

logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])

# === 调度参数（修改后需重启进程）===
DAILY_SCHEDULE_HOUR = 18
DAILY_SCHEDULE_MINUTE = 0
US_PREMARKET_NEWS_SCHEDULE_HOUR = 20
US_PREMARKET_NEWS_SCHEDULE_MINUTE = 0
MARKET_CALENDAR_SCHEDULE_HOUR = 19
MARKET_CALENDAR_SCHEDULE_MINUTE = 0
US_PREMARKET_SCHEDULE_HOUR = 21
US_PREMARKET_SCHEDULE_MINUTE = 0
INTRADAY_ANALYSIS_INTERVAL_MINUTES = 15
SCHEDULE_TIMEZONE = "Asia/Shanghai"
RUN_IMMEDIATELY_ON_STARTUP = False

_JOB_DAILY_ANALYSIS = "analysis_daily"
_JOB_MARKET_CALENDAR = "market_calendar"
_JOB_US_PREMARKET_NEWS = "analysis_us_premarket_news"
_JOB_US_PREMARKET_ANALYSIS = "analysis_us_premarket"
_JOB_US_INTRADAY_ANALYSIS = "analysis_us_intraday"
_JOB_A_SHARE_INTRADAY_ANALYSIS = "analysis_a_share_intraday"

_EMBEDDED_SCHEDULER: Optional[Any] = None


@dataclass(frozen=True)
class ScheduledTaskDefinition:
    job_id: str
    name: str
    description: str
    task_type: str
    schedule: str
    timezone: str
    allow_manual_run: bool
    func: Callable[..., Any]


def _with_task_tracking(task_type: str, task_name: str, scheduler_job_id: str) -> Callable[[F], F]:
    """Track one APScheduler execution instance in logs and the task table."""
    return track_task(
        task_type=task_type,
        task_name=task_name,
        source="apscheduler",
        trigger_source="scheduler",
        task_id_getter=lambda **kwargs: kwargs.get("task_id"),
        trigger_source_getter=lambda **kwargs: kwargs.get("_trigger_source") or "scheduler",
        triggered_by_uid_getter=lambda **kwargs: kwargs.get("_triggered_by_uid"),
        scheduler_job_id=scheduler_job_id,
        record_result=True,
        success_message="定时任务执行完成",
        strip_lifecycle_kwargs=True,
    )


def _scheduled_now() -> datetime:
    """Return scheduler-local current time for calendar grouping."""
    return datetime.now(ZoneInfo(SCHEDULE_TIMEZONE))


def _resolve_report_type(config: Any):
    """Resolve configured report type using the same mapping as the pipeline."""
    from finance_analysis.reporting.types import ReportType

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
    from finance_analysis.database.repositories.calendar import CalendarRepo
    from finance_analysis.database.repositories.user import UserRepository

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


@_with_task_tracking("scheduled_daily", "每日全量分析", _JOB_DAILY_ANALYSIS)
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
        from finance_analysis.analysis.pipeline_config import get_pipeline_config
        from finance_analysis.analysis.pipeline import StockAnalysisPipeline
        from finance_analysis.database.repositories.watch_list import get_watch_list_codes

        config = get_pipeline_config()
        stock_codes = get_watch_list_codes()
        total_count = len(stock_codes)
        if not stock_codes:
            finished_at = _scheduled_now()
            _safe_record_scheduled_task_result(
                task_name=task_name,
                type="scheduled_daily",
                started_at=started_at,
                finished_at=finished_at,
                total_count=0,
                results=[],
                note="未配置自选股，本次每日全量分析已跳过。",
            )
            raise TaskSkipped("未配置自选股，本次每日全量分析已跳过")
        pipeline = StockAnalysisPipeline(config=config)
        results = pipeline.run(stock_codes=stock_codes)
        if results:
            report = pipeline._generate_aggregate_report(results, _resolve_report_type(config))
    except TaskSkipped:
        raise
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
        raise
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


@_with_task_tracking("scheduled_us_premarket", "美股盘前分析", _JOB_US_PREMARKET_ANALYSIS)
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
        from finance_analysis.analysis.pipeline_config import get_pipeline_config
        from finance_analysis.analysis.pipeline import StockAnalysisPipeline
        from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market

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
            raise TaskSkipped("未配置美股自选股，本次定时任务已跳过")

        config = get_pipeline_config()
        pipeline = StockAnalysisPipeline(config=config)
        results = pipeline.run(stock_codes=stock_codes)
        if results:
            report = pipeline._generate_aggregate_report(results, _resolve_report_type(config))
    except TaskSkipped:
        raise
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
        raise
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


@_with_task_tracking("scheduled_us_premarket_news", "美股盘前新闻情报", _JOB_US_PREMARKET_NEWS)
def _us_premarket_news_task() -> None:
    """美股盘前新闻情报任务：每天运行，抓取自选股和 Nasdaq-100 前 20 新闻。"""
    task_name = "美股盘前新闻情报"
    started_at = _scheduled_now()
    logger.info("=" * 50)
    logger.info("美股盘前新闻情报任务开始执行 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 50)
    total_count = 0
    try:
        from finance_analysis.analysis.pipeline_config import get_pipeline_config
        from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market
        from finance_analysis.tasks.jobs.us_premarket_news.service import USPremarketNewsService

        watch_symbols = get_watch_list_codes_by_market("US")
        service = USPremarketNewsService(config=get_pipeline_config())
        summary = service.run(watch_symbols, now=started_at)
        total_count = summary.symbols_count
    except Exception as exc:
        finished_at = _scheduled_now()
        logger.exception("美股盘前新闻情报任务执行失败: %s", exc)
        _safe_record_scheduled_task_result(
            task_name=task_name,
            type="scheduled_us_premarket_news",
            started_at=started_at,
            finished_at=finished_at,
            total_count=total_count,
            results=[],
            error=str(exc),
        )
        raise
    else:
        logger.info(
            "美股盘前新闻情报任务执行完成 - %s",
            _scheduled_now().strftime("%Y-%m-%d %H:%M:%S"),
        )


@_with_task_tracking("scheduled_market_calendar", "美股财经日历同步", _JOB_MARKET_CALENDAR)
def _market_calendar_task() -> None:
    """美股财经日历定时任务：每天同步未来财经事件。"""
    started_at = _scheduled_now()
    logger.info("=" * 50)
    logger.info("美股财经日历任务开始执行 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 50)
    try:
        from finance_analysis.tasks.jobs.market_calendar_sync import MarketCalendarSyncService

        summary = MarketCalendarSyncService().run(now=started_at)
        if summary.all_interfaces_failed:
            logger.error("美股财经日历任务失败：所有接口均失败 errors=%s", summary.errors)
            raise RuntimeError(f"美股财经日历任务失败：所有接口均失败 errors={summary.errors}")
        else:
            logger.info(
                "美股财经日历任务完成: fetched=%s inserted=%s updated=%s duplicate=%s notify=%s",
                summary.fetched_count_by_type,
                summary.inserted_count,
                summary.updated_count,
                summary.skipped_duplicate_count,
                summary.notification_sent_count,
            )
    except Exception as exc:
        logger.exception("美股财经日历任务执行失败: %s", exc)
        raise


@_with_task_tracking("scheduled_us_intraday", "美股盘中分析", _JOB_US_INTRADAY_ANALYSIS)
def _us_intraday_analysis_task() -> None:
    """美股盘中定时任务：检测自选美股的盘中异动并按需提醒。"""
    started_at = _scheduled_now()
    logger.info("美股盘中分析任务触发 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        from finance_analysis.analysis.pipeline_config import get_pipeline_config
        from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market
        from finance_analysis.tasks.jobs.us_intraday_analysis import USIntradayAnalysisService

        stock_codes = get_watch_list_codes_by_market("US")
        if not stock_codes:
            logger.info("未配置美股自选股，跳过美股盘中分析任务")
            raise TaskSkipped("未配置美股自选股，跳过美股盘中分析任务")

        service = USIntradayAnalysisService(config=get_pipeline_config())
        summary = service.run(stock_codes)
        if not summary.market_open:
            logger.info("当前不是美股盘中交易时段，跳过美股盘中分析任务")
            raise TaskSkipped("当前不是美股盘中交易时段，跳过美股盘中分析任务")

        logger.info(
            "美股盘中分析完成: total=%s processed=%s skipped=%s candidates=%s signals=%s errors=%s",
            summary.total_symbols,
            summary.processed_symbols,
            summary.skipped_symbols,
            summary.candidate_count,
            len(summary.signal_results),
            len(summary.errors),
        )
    except TaskSkipped:
        raise
    except Exception as exc:
        logger.exception("美股盘中分析任务执行失败: %s", exc)
        raise


@_with_task_tracking("scheduled_a_share_intraday", "A股盘中分析", _JOB_A_SHARE_INTRADAY_ANALYSIS)
def _a_share_intraday_analysis_task() -> None:
    """A 股盘中定时任务：任务流程暂为空。"""
    logger.info(
        "A股盘中分析任务触发 - %s（任务流程暂为空）",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    raise TaskSkipped("A股盘中分析任务流程暂为空，本次执行已跳过")


def get_scheduled_task_definitions() -> List[ScheduledTaskDefinition]:
    """Return code-defined APScheduler jobs and their display metadata."""
    return [
        ScheduledTaskDefinition(
            job_id=_JOB_DAILY_ANALYSIS,
            name="每日全量分析",
            description="分析自选股中的全部股票并生成汇总报告",
            task_type="scheduled_daily",
            schedule=f"每天 {DAILY_SCHEDULE_HOUR:02d}:{DAILY_SCHEDULE_MINUTE:02d}",
            timezone=SCHEDULE_TIMEZONE,
            allow_manual_run=True,
            func=_daily_analysis_task,
        ),
        ScheduledTaskDefinition(
            job_id=_JOB_MARKET_CALENDAR,
            name="美股财经日历同步",
            description="同步未来美股财经事件并更新事件日历",
            task_type="scheduled_market_calendar",
            schedule=f"每天 {MARKET_CALENDAR_SCHEDULE_HOUR:02d}:{MARKET_CALENDAR_SCHEDULE_MINUTE:02d}",
            timezone=SCHEDULE_TIMEZONE,
            allow_manual_run=True,
            func=_market_calendar_task,
        ),
        ScheduledTaskDefinition(
            job_id=_JOB_US_PREMARKET_NEWS,
            name="美股盘前新闻情报",
            description="抓取自选股和 Nasdaq-100 前 20 新闻并生成盘前情报",
            task_type="scheduled_us_premarket_news",
            schedule=f"每天 {US_PREMARKET_NEWS_SCHEDULE_HOUR:02d}:{US_PREMARKET_NEWS_SCHEDULE_MINUTE:02d}",
            timezone=SCHEDULE_TIMEZONE,
            allow_manual_run=True,
            func=_us_premarket_news_task,
        ),
        ScheduledTaskDefinition(
            job_id=_JOB_US_PREMARKET_ANALYSIS,
            name="美股盘前分析",
            description="分析自选股中的美股并生成盘前报告",
            task_type="scheduled_us_premarket",
            schedule=f"每天 {US_PREMARKET_SCHEDULE_HOUR:02d}:{US_PREMARKET_SCHEDULE_MINUTE:02d}",
            timezone=SCHEDULE_TIMEZONE,
            allow_manual_run=True,
            func=_us_premarket_analysis_task,
        ),
        ScheduledTaskDefinition(
            job_id=_JOB_US_INTRADAY_ANALYSIS,
            name="美股盘中分析",
            description="检测自选美股盘中异动并按需提醒",
            task_type="scheduled_us_intraday",
            schedule=f"每 {INTRADAY_ANALYSIS_INTERVAL_MINUTES} 分钟",
            timezone=SCHEDULE_TIMEZONE,
            allow_manual_run=True,
            func=_us_intraday_analysis_task,
        ),
        ScheduledTaskDefinition(
            job_id=_JOB_A_SHARE_INTRADAY_ANALYSIS,
            name="A股盘中分析",
            description="A 股盘中分析任务占位流程，当前执行后会记录为跳过",
            task_type="scheduled_a_share_intraday",
            schedule=f"每 {INTRADAY_ANALYSIS_INTERVAL_MINUTES} 分钟",
            timezone=SCHEDULE_TIMEZONE,
            allow_manual_run=False,
            func=_a_share_intraday_analysis_task,
        ),
    ]


def get_scheduled_task_definition(job_id: str) -> Optional[ScheduledTaskDefinition]:
    definitions = {item.job_id: item for item in get_scheduled_task_definitions()}
    return definitions.get(job_id)


def get_embedded_analysis_scheduler() -> Optional[Any]:
    """Return the scheduler instance started by FastAPI lifespan, if available."""
    return _EMBEDDED_SCHEDULER


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

    global _EMBEDDED_SCHEDULER

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
        _market_calendar_task,
        CronTrigger(
            hour=MARKET_CALENDAR_SCHEDULE_HOUR,
            minute=MARKET_CALENDAR_SCHEDULE_MINUTE,
            timezone=SCHEDULE_TIMEZONE,
        ),
        id=_JOB_MARKET_CALENDAR,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _us_premarket_news_task,
        CronTrigger(
            hour=US_PREMARKET_NEWS_SCHEDULE_HOUR,
            minute=US_PREMARKET_NEWS_SCHEDULE_MINUTE,
            timezone=SCHEDULE_TIMEZONE,
        ),
        id=_JOB_US_PREMARKET_NEWS,
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
    _EMBEDDED_SCHEDULER = scheduler
    logger.info(
        "APScheduler 已启动，每日定时任务: %02d:%02d，财经日历: %02d:%02d，"
        "美股盘前新闻: %02d:%02d，"
        "美股盘前分析: %02d:%02d，"
        "美股盘中分析/A股盘中分析: 每 %d 分钟一次 (%s)",
        DAILY_SCHEDULE_HOUR,
        DAILY_SCHEDULE_MINUTE,
        MARKET_CALENDAR_SCHEDULE_HOUR,
        MARKET_CALENDAR_SCHEDULE_MINUTE,
        US_PREMARKET_NEWS_SCHEDULE_HOUR,
        US_PREMARKET_NEWS_SCHEDULE_MINUTE,
        US_PREMARKET_SCHEDULE_HOUR,
        US_PREMARKET_SCHEDULE_MINUTE,
        INTRADAY_ANALYSIS_INTERVAL_MINUTES,
        SCHEDULE_TIMEZONE,
    )
    job = scheduler.get_job(_JOB_DAILY_ANALYSIS)
    if job is not None and job.next_run_time is not None:
        logger.info("下次执行时间: %s", job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))
    market_calendar_job = scheduler.get_job(_JOB_MARKET_CALENDAR)
    if market_calendar_job is not None and market_calendar_job.next_run_time is not None:
        logger.info(
            "财经日历任务下次执行时间: %s",
            market_calendar_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"),
        )

    if RUN_IMMEDIATELY_ON_STARTUP:
        logger.info("启动时立即执行一次定时任务...")
        try:
            _daily_analysis_task()
        except Exception as exc:
            logger.exception("启动时立即执行任务失败: %s", exc)

    return scheduler


def shutdown_embedded_analysis_scheduler(scheduler) -> None:
    """停机时调用：等待运行中的任务完成后停止调度器。"""
    global _EMBEDDED_SCHEDULER
    if scheduler is None:
        return
    try:
        scheduler.shutdown(wait=True)
    finally:
        if _EMBEDDED_SCHEDULER is scheduler:
            _EMBEDDED_SCHEDULER = None
        logger.info("APScheduler 已停止")

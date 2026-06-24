# -*- coding: utf-8 -*-
"""Plain business runners for the periodic scheduled tasks.

These functions contain the actual analysis/ingestion work that used to live in
the APScheduler module. They are intentionally framework-agnostic: they take no
scheduler/Celery context, return JSON-serializable results, and raise
:class:`TaskSkipped` when a run should be recorded as skipped. The Celery task
wrappers in :mod:`finance_analysis.tasks.celery.jobs.scheduled` add lifecycle
tracking on top of them.

The exchange trading-day, trading-session, lunch-break, and close checks remain
inside each business service; nothing here simulates a trading calendar.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional, Sequence
from zoneinfo import ZoneInfo

from finance_analysis.tasks.celery.schedule import SCHEDULE_TIMEZONE, US_TIMEZONE
from finance_analysis.tasks.lifecycle import TaskSkipped

logger = logging.getLogger(__name__)


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
    """Best-effort calendar recording; never fail the task because of UI history."""
    try:
        _record_scheduled_task_result(**kwargs)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("写入定时任务日历记录失败: %s", exc, exc_info=True)


def run_daily_analysis() -> None:
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


def run_us_premarket_analysis() -> None:
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


def run_us_premarket_news() -> None:
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


def run_market_calendar() -> None:
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


def run_us_intraday_analysis() -> None:
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


def run_us_postmarket_review() -> dict:
    """美股收盘后生成指数、板块、自选股和新闻复盘报告。"""
    started_at = datetime.now(ZoneInfo(US_TIMEZONE))
    logger.info("美股收盘复盘任务触发 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S %Z"))
    try:
        from finance_analysis.analysis.pipeline_config import get_pipeline_config
        from finance_analysis.tasks.jobs.us_postmarket_review import USPostmarketReviewService

        service = USPostmarketReviewService(config=get_pipeline_config())
        summary = service.run(send_notification=True)
        return summary.to_dict()
    except TaskSkipped:
        raise
    except Exception as exc:
        logger.exception("美股收盘复盘任务执行失败: %s", exc)
        raise


def run_a_share_intraday_analysis() -> dict:
    """A 股盘中定时任务：识别市场情绪、板块轮动与自选股异动并按需提醒。"""
    started_at = _scheduled_now()
    logger.info("A股盘中分析任务触发 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S %Z"))
    try:
        from finance_analysis.analysis.pipeline_config import get_pipeline_config
        from finance_analysis.tasks.jobs.a_share_intraday_analysis import (
            AShareIntradayAnalysisService,
        )

        service = AShareIntradayAnalysisService(config=get_pipeline_config())
        summary = service.run(send_notification=True)
        return summary.to_dict()
    except TaskSkipped:
        raise
    except Exception as exc:
        logger.exception("A股盘中分析任务执行失败: %s", exc)
        raise


__all__ = [
    "run_a_share_intraday_analysis",
    "run_daily_analysis",
    "run_market_calendar",
    "run_us_intraday_analysis",
    "run_us_postmarket_review",
    "run_us_premarket_analysis",
    "run_us_premarket_news",
]

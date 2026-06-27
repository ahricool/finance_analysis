"""Shared helpers for periodic task services."""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any, List, Optional, Sequence
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


def safe_record_scheduled_task_result(**kwargs: Any) -> None:
    try:
        _record_scheduled_task_result(**kwargs)
    except Exception as exc:  # pragma: no cover - defensive best effort
        logger.warning("写入定时任务日历记录失败: %s", exc, exc_info=True)


def _result_summary_lines(results: Sequence[Any]) -> List[str]:
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
    elapsed = (finished_at - started_at).total_seconds()
    lines = [
        f"## {task_name}",
        "",
        f"- 执行状态：{status}",
        f"- 开始时间：{started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 结束时间：{finished_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 耗时：{elapsed:.2f} 秒",
        f"- 计划分析数量：{total_count}",
        f"- 成功数量：{len(results)}",
        f"- 失败/未产出数量：{max(total_count - len(results), 0)}",
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
    from finance_analysis.database.repositories.calendar import CalendarRepo
    from finance_analysis.database.repositories.user import UserRepository

    status = "失败" if error else ("跳过" if total_count == 0 else "完成")
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
        title=f"{task_name}{status}：成功 {len(results)} / 总计 {total_count}"[:120],
        content=content,
        type=type,
    )


__all__ = [
    "INTRADAY_START_DELAY_MAX_SECONDS",
    "resolve_report_type",
    "safe_record_scheduled_task_result",
    "scheduled_now",
    "sleep_random_start_delay",
]

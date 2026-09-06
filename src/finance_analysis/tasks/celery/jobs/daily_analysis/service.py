"""Business service for daily watch-list analysis."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from finance_analysis.tasks.celery.schedule import JOB_DAILY_ANALYSIS, require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import TaskSkipped

from ..scheduled_support import resolve_report_type, scheduled_now

logger = logging.getLogger(__name__)
DEFINITION = require_scheduled_task_definition(JOB_DAILY_ANALYSIS)


class DailyAnalysisTaskService:
    task_name = DEFINITION.name
    task_type = DEFINITION.task_type

    def run(self) -> dict[str, Any]:
        started_at = scheduled_now()
        logger.info("每日全量分析任务开始执行 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
        results: List[Any] = []
        total_count = 0
        report: Optional[str] = None
        try:
            from finance_analysis.analysis.pipeline import StockAnalysisPipeline
            from finance_analysis.analysis.pipeline_config import get_pipeline_config
            from finance_analysis.database.repositories.watch_list import get_watch_list_codes

            config = get_pipeline_config()
            stock_codes = get_watch_list_codes()
            total_count = len(stock_codes)
            if not stock_codes:
                raise TaskSkipped("未配置自选股，本次每日全量分析已跳过")
            pipeline = StockAnalysisPipeline(config=config)
            results = pipeline.run(stock_codes=stock_codes)
            if results:
                report = pipeline._generate_aggregate_report(results, resolve_report_type(config))
        except TaskSkipped:
            raise
        except Exception as exc:
            logger.exception("每日全量分析任务执行失败: %s", exc)
            raise
        else:
            finished_at = scheduled_now()
            logger.info("每日全量分析任务执行完成 - %s", finished_at.strftime("%Y-%m-%d %H:%M:%S"))
            return {
                "total_count": total_count,
                "success_count": len(results),
                "failed_count": max(0, total_count - len(results)),
                "report": report,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
            }


__all__ = ["DailyAnalysisTaskService"]

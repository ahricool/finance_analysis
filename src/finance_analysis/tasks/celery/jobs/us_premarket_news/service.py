"""Business service for scheduled US premarket news intelligence."""

from __future__ import annotations

import logging

from finance_analysis.tasks.celery.schedule import JOB_US_PREMARKET_NEWS, require_scheduled_task_definition

from ..scheduled_support import safe_record_scheduled_task_result, scheduled_now

logger = logging.getLogger(__name__)
DEFINITION = require_scheduled_task_definition(JOB_US_PREMARKET_NEWS)


class USPremarketNewsTaskService:
    task_name = DEFINITION.name
    task_type = DEFINITION.task_type

    def run(self) -> None:
        started_at = scheduled_now()
        logger.info("美股盘前新闻情报任务开始执行 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
        total_count = 0
        try:
            from finance_analysis.analysis.pipeline_config import get_pipeline_config
            from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market
            from finance_analysis.tasks.jobs.us_premarket_news.service import USPremarketNewsService

            watch_symbols = get_watch_list_codes_by_market("US")
            summary = USPremarketNewsService(config=get_pipeline_config()).run(watch_symbols, now=started_at)
            total_count = summary.symbols_count
        except Exception as exc:
            logger.exception("美股盘前新闻情报任务执行失败: %s", exc)
            safe_record_scheduled_task_result(
                task_name=self.task_name,
                type=self.task_type,
                started_at=started_at,
                finished_at=scheduled_now(),
                total_count=total_count,
                results=[],
                error=str(exc),
            )
            raise
        logger.info("美股盘前新闻情报任务执行完成 - %s", scheduled_now().strftime("%Y-%m-%d %H:%M:%S"))


__all__ = ["USPremarketNewsTaskService"]

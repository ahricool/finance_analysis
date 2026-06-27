"""Business service for scheduled US intraday analysis."""

from __future__ import annotations

import logging
from typing import Any

from finance_analysis.tasks.lifecycle import TaskSkipped

from ..scheduled_support import scheduled_now, sleep_random_start_delay

logger = logging.getLogger(__name__)


class USIntradayAnalysisTaskService:
    def run(self) -> dict[str, Any]:
        sleep_random_start_delay(task_name="美股盘中分析任务")
        started_at = scheduled_now()
        logger.info("美股盘中分析任务触发 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
        try:
            from finance_analysis.analysis.pipeline_config import get_pipeline_config
            from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market
            from finance_analysis.tasks.jobs.us_intraday_analysis import USIntradayAnalysisService

            stock_codes = get_watch_list_codes_by_market("US")
            if not stock_codes:
                raise TaskSkipped("未配置美股自选股，跳过美股盘中分析任务")
            summary = USIntradayAnalysisService(config=get_pipeline_config()).run(stock_codes)
            if not summary.market_open:
                raise TaskSkipped("当前不是美股盘中交易时段，跳过美股盘中分析任务")
            logger.info(
                "美股盘中分析完成: total=%s processed=%s stale=%s skipped=%s candidates=%s "
                "llm_candidates=%s signals=%s notifications=%s duration=%ss filter_failures=%s",
                summary.total_symbols,
                summary.processed_symbols,
                summary.stale_symbols,
                summary.skipped_symbols,
                summary.candidate_count,
                summary.llm_candidate_count,
                len(summary.signal_results),
                summary.notification_count,
                summary.timings.get("duration_seconds"),
                summary.filter_failure_counts,
            )
            return summary.to_dict()
        except TaskSkipped:
            raise
        except Exception as exc:
            logger.exception("美股盘中分析任务执行失败: %s", exc)
            raise


__all__ = ["USIntradayAnalysisTaskService"]

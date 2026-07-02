"""Celery orchestration for scheduled A-share intraday analysis."""

from __future__ import annotations

import logging
from typing import Any

from finance_analysis.tasks.lifecycle import TaskSkipped

from ..scheduled_support import scheduled_now, sleep_random_start_delay

logger = logging.getLogger(__name__)


class AShareIntradayAnalysisTaskService:
    def run(self) -> dict[str, Any]:
        sleep_random_start_delay(task_name="A股盘中分析任务")
        started_at = scheduled_now()
        logger.info("A股盘中分析任务触发 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S %Z"))
        try:
            from finance_analysis.analysis.pipeline_config import get_pipeline_config

            from .domain_service import AShareIntradayAnalysisService

            summary = AShareIntradayAnalysisService(config=get_pipeline_config()).run(send_notification=True)
            return summary.to_dict()
        except TaskSkipped:
            raise
        except Exception as exc:
            logger.exception("A股盘中分析任务执行失败: %s", exc)
            raise


__all__ = ["AShareIntradayAnalysisTaskService"]

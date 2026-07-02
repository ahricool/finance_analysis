"""Celery orchestration for scheduled US postmarket review."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from finance_analysis.tasks.celery.schedule import US_TIMEZONE
from finance_analysis.tasks.lifecycle import TaskSkipped

logger = logging.getLogger(__name__)


class USPostmarketReviewTaskService:
    def run(self) -> dict[str, Any]:
        started_at = datetime.now(ZoneInfo(US_TIMEZONE))
        logger.info("美股收盘复盘任务触发 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S %Z"))
        try:
            from finance_analysis.analysis.pipeline_config import get_pipeline_config

            from .domain_service import USPostmarketReviewService

            summary = USPostmarketReviewService(config=get_pipeline_config()).run(send_notification=True)
            return summary.to_dict()
        except TaskSkipped:
            raise
        except Exception as exc:
            logger.exception("美股收盘复盘任务执行失败: %s", exc)
            raise


__all__ = ["USPostmarketReviewTaskService"]

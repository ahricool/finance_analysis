"""Business adapter for market-calendar importance scoring."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from finance_analysis.tasks.celery.jobs.market_calendar_sync.importance import (
    MarketCalendarImportanceService,
)

logger = logging.getLogger(__name__)


class MarketCalendarImportanceTaskService:
    def run(self, event_ids: Sequence[int]) -> dict[str, Any]:
        ids = [int(event_id) for event_id in event_ids if event_id is not None]
        if not ids:
            return {"requested": 0, "scored": 0, "skipped": 0, "errors": []}
        logger.info("财经日历重要性评分任务开始: event_ids=%s", ids)
        return MarketCalendarImportanceService().score_event_ids(ids)


__all__ = ["MarketCalendarImportanceTaskService"]

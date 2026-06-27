"""Business service for scheduled market-calendar synchronization."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from finance_analysis.tasks.celery.schedule import QUEUE_INGESTION

from ..scheduled_support import scheduled_now

logger = logging.getLogger(__name__)


class MarketCalendarSyncTaskService:
    def run(self) -> dict[str, Any]:
        started_at = scheduled_now()
        logger.info("美股财经日历任务开始执行 - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
        try:
            from finance_analysis.tasks.jobs.market_calendar_sync import MarketCalendarSyncService

            summary = MarketCalendarSyncService().run(now=started_at)
            if summary.all_interfaces_failed:
                raise RuntimeError(f"美股财经日历任务失败：所有接口均失败 errors={summary.errors}")
            importance_candidate_ids = list(getattr(summary, "importance_candidate_ids", []) or [])
            self._submit_importance_task(importance_candidate_ids)
            logger.info(
                "美股财经日历任务完成: fetched=%s inserted=%s updated=%s duplicate=%s notify=%s "
                "importance_candidates=%s",
                summary.fetched_count_by_type,
                summary.inserted_count,
                summary.updated_count,
                summary.skipped_duplicate_count,
                summary.notification_sent_count,
                len(importance_candidate_ids),
            )
            if hasattr(summary, "to_dict"):
                return summary.to_dict()
            return {
                "fetched_count_by_type": dict(getattr(summary, "fetched_count_by_type", {}) or {}),
                "inserted_count": int(getattr(summary, "inserted_count", 0) or 0),
                "updated_count": int(getattr(summary, "updated_count", 0) or 0),
                "skipped_duplicate_count": int(getattr(summary, "skipped_duplicate_count", 0) or 0),
                "notification_sent_count": int(getattr(summary, "notification_sent_count", 0) or 0),
                "importance_candidate_ids": importance_candidate_ids,
            }
        except Exception as exc:
            logger.exception("美股财经日历任务执行失败: %s", exc)
            raise

    @staticmethod
    def _submit_importance_task(event_ids: Sequence[int]) -> None:
        ids = [int(event_id) for event_id in event_ids if event_id is not None]
        if not ids:
            return
        try:
            from finance_analysis.tasks.celery.jobs.market_calendar_importance.tasks import (
                market_calendar_importance,
            )

            market_calendar_importance.apply_async(kwargs={"event_ids": ids}, queue=QUEUE_INGESTION)
            logger.info("已投递财经日历重要性评分任务: count=%s", len(ids))
        except Exception as exc:
            logger.warning("投递财经日历重要性评分任务失败: %s", exc, exc_info=True)


__all__ = ["MarketCalendarSyncTaskService"]

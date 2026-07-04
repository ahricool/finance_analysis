"""Celery entry point for US historical market-data synchronization."""

from __future__ import annotations

from typing import Any, Optional

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import JOB_US_MARKET_DATA_SYNC, require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task

from .service import USMarketDataSyncService

DEFINITION = require_scheduled_task_definition(JOB_US_MARKET_DATA_SYNC)


@celery_app.task(name=DEFINITION.celery_task_name)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
    dedupe_key=f"scheduled:{DEFINITION.job_id}",
)
def sync_us_market_data(scheduler_job_id: Optional[str] = None, **_: Any) -> dict[str, Any]:
    del scheduler_job_id
    return USMarketDataSyncService().run()


__all__ = ["sync_us_market_data"]

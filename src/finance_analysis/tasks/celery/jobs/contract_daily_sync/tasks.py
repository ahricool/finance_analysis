"""Tracked daily contract history sync."""
import asyncio

import httpx

from finance_analysis.contracts.daily_sync import DailySyncError, run_daily_sync
from finance_analysis.tasks.advisory_lock import TaskAdvisoryLockId
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task

DEFINITION = require_scheduled_task_definition("contract_daily_sync")


@celery_app.task(
    name=DEFINITION.celery_task_name,
    autoretry_for=(DailySyncError, httpx.HTTPError),
    retry_kwargs={"max_retries": 3},
    default_retry_delay=600,
)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
    advisory_lock_id=TaskAdvisoryLockId.CONTRACT_DAILY_SYNC,
    advisory_lock_blocking=False,
)
def sync_contract_daily(**kwargs):
    return asyncio.run(run_daily_sync())

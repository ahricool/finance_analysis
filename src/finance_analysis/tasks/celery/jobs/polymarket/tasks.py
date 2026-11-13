"""Catalog task using a session advisory lock, with no long write transaction."""

from finance_analysis.prediction_markets.service import Service
from finance_analysis.tasks.advisory_lock import TaskAdvisoryLockId
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task, TaskOutcome, TaskExecutionStatus

CATALOG = require_scheduled_task_definition("polymarket_catalog_sync")


def outcome(result):
    if result.get("status") in {"partial", "failed"}:
        return TaskOutcome(TaskExecutionStatus(result["status"]), "Polymarket部分项目失败，可在任务结果查看统计并重试")
    return None


@celery_app.task(name=CATALOG.celery_task_name)
@track_task(
    task_type=CATALOG.task_type,
    task_name=CATALOG.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CATALOG.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
    advisory_lock_id=TaskAdvisoryLockId.POLYMARKET,
    advisory_lock_blocking=False,
    outcome_getter=outcome,
)
def polymarket_catalog_sync(slug=None, **kwargs):
    service = Service()
    try:
        result = service.catalog(slug)
        return result
    finally:
        service.client.close()

"""Two tracked tasks sharing a session advisory lock, with no long write transaction."""

from finance_analysis.prediction_markets.service import Service
from finance_analysis.prediction_markets.config import get_config
from finance_analysis.tasks.advisory_lock import TaskAdvisoryLockId
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task, TaskOutcome, TaskExecutionStatus, TaskSkipped

CATALOG = require_scheduled_task_definition("polymarket_catalog_sync")
MATCH = require_scheduled_task_definition("polymarket_stock_matching")


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
    if not get_config().enabled:
        raise TaskSkipped("事件预测功能未启用")
    service = Service()
    try:
        result = service.catalog(slug)
        if result["status"] != "failed":
            polymarket_stock_matching.apply_async(queue=MATCH.queue, countdown=5)
        return result
    finally:
        service.client.close()


@celery_app.task(name=MATCH.celery_task_name)
@track_task(
    task_type=MATCH.task_type,
    task_name=MATCH.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=MATCH.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
    advisory_lock_id=TaskAdvisoryLockId.POLYMARKET,
    advisory_lock_blocking=False,
    outcome_getter=outcome,
)
def polymarket_stock_matching(retry_event_id=None, retry=False, **kwargs):
    if not get_config().enabled:
        raise TaskSkipped("事件预测功能未启用")
    service = Service()
    try:
        if retry:
            service.repo.retry(retry_event_id)
        return service.match()
    finally:
        service.client.close()

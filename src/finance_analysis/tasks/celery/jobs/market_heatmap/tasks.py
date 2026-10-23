"""Independent market locks and task-center lifecycle for heatmap refreshes."""

from finance_analysis.market_heatmap.service import HeatmapService
from finance_analysis.tasks.advisory_lock import TaskAdvisoryLockId
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task

CN = require_scheduled_task_definition("market_heatmap_cn")
US = require_scheduled_task_definition("market_heatmap_us")


@celery_app.task(name=CN.celery_task_name)
@track_task(task_type=CN.task_type, task_name=CN.name, source="celery", trigger_source="scheduler",
            scheduler_job_id=CN.job_id, record_result=True, strip_lifecycle_kwargs=True,
            advisory_lock_id=TaskAdvisoryLockId.MARKET_HEATMAP_CN, advisory_lock_blocking=False)
def refresh_market_heatmap_cn(**kwargs):
    return HeatmapService().refresh("CN")


@celery_app.task(name=US.celery_task_name)
@track_task(task_type=US.task_type, task_name=US.name, source="celery", trigger_source="scheduler",
            scheduler_job_id=US.job_id, record_result=True, strip_lifecycle_kwargs=True,
            advisory_lock_id=TaskAdvisoryLockId.MARKET_HEATMAP_US, advisory_lock_blocking=False)
def refresh_market_heatmap_us(**kwargs):
    return HeatmapService().refresh("US")

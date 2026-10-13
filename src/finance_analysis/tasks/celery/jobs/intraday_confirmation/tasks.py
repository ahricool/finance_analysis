"""Two bounded, lifecycle-tracked tasks on the existing alerts queue."""

from finance_analysis.intraday_confirmation.service import ConfirmationService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import TaskSkipped, track_task


def _run(market):
    result = ConfirmationService().run(market)
    if result["status"] == "skipped":
        raise TaskSkipped(result["reason"])
    return result


CN = require_scheduled_task_definition("intraday_confirmation_cn")
US = require_scheduled_task_definition("intraday_confirmation_us")


@celery_app.task(name=CN.celery_task_name, soft_time_limit=480, time_limit=540)
@track_task(
    task_type=CN.task_type,
    task_name=CN.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def run_intraday_confirmation_cn(**kwargs):
    return _run("CN")


@celery_app.task(name=US.celery_task_name, soft_time_limit=480, time_limit=540)
@track_task(
    task_type=US.task_type,
    task_name=US.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=US.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def run_intraday_confirmation_us(**kwargs):
    return _run("US")

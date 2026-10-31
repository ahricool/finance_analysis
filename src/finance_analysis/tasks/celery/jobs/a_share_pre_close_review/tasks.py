"""CN 14:10 private holdings reviews; shared workflow with the US adapter."""

from finance_analysis.tasks.celery.jobs.holdings_review_support import run_review, review_outcome
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task

DEFINITION = require_scheduled_task_definition("analysis_a_share_pre_close_review")


@celery_app.task(name=DEFINITION.celery_task_name, expires=DEFINITION.expires)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
    uid_getter=lambda **kwargs: kwargs.get("uid"),
    outcome_getter=review_outcome,
)
def analysis_a_share_pre_close_review(uid=None, **kwargs):
    return run_review(analysis_a_share_pre_close_review, "CN", uid)

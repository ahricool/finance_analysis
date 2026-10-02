"""Tracked asynchronous adapters; research never blocks calendar ingestion."""

from finance_analysis.earnings_outlook.service import EarningsOutlookService
from finance_analysis.earnings_outlook.rules import event_window, released
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.metadata import EARNINGS_OUTLOOK_TASK
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task


def _run_outlook(stage, event_id=None):
    service = EarningsOutlookService()
    result = service.run(stage=stage, event_id=event_id)
    # Retry only contended events, retaining the original target even across midnight.
    # Broker expiry and the service's release check both forbid post-release forecasts.
    for item in result.get("results", []):
        if item["status"] != "busy":
            continue
        event = service.repo.event(item["event_id"])
        now = service.clock()
        window = event_window(event)
        if released(event, now, window):
            item["status"] = "frozen"
            continue
        earnings_outlook.apply_async(
            kwargs={"event_id": event.id, "stage": stage},
            countdown=min(60, (window["cutoff"] - now).total_seconds() / 2),
            expires=window["cutoff"],
        )
        item["status"] = "deferred"
    return result


@celery_app.task(name=EARNINGS_OUTLOOK_TASK.celery_name)
@track_task(
    task_type=EARNINGS_OUTLOOK_TASK.task_type,
    task_name=EARNINGS_OUTLOOK_TASK.display_name,
    source="celery",
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def earnings_outlook(event_id=None, stage="daily", **kwargs):
    return _run_outlook(stage, event_id)


FINAL = require_scheduled_task_definition("earnings_outlook_final")
REVIEW = require_scheduled_task_definition("earnings_outlook_review")


@celery_app.task(name=FINAL.celery_task_name)
@track_task(
    task_type=FINAL.task_type,
    task_name=FINAL.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=FINAL.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def earnings_outlook_final(**kwargs):
    return _run_outlook("final")


@celery_app.task(name=REVIEW.celery_task_name)
@track_task(
    task_type=REVIEW.task_type,
    task_name=REVIEW.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=REVIEW.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def earnings_outlook_review(**kwargs):
    return EarningsOutlookService().review()

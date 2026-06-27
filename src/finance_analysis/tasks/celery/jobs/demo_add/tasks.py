"""Celery entry point for the demo addition task."""

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.metadata import DEMO_ADD_TASK
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name=DEMO_ADD_TASK.celery_name)
@track_task(
    task_type=DEMO_ADD_TASK.task_type,
    task_name=DEMO_ADD_TASK.display_name,
    source=DEMO_ADD_TASK.source,
    record_result=True,
    success_message="Demo task completed",
)
def add(x: float, y: float) -> float:
    return x + y


__all__ = ["add"]

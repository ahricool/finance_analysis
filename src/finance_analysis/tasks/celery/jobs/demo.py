# -*- coding: utf-8 -*-
"""Demo Celery tasks for integration smoke tests."""

from __future__ import annotations

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name="demo.add")
@track_task(
    task_type="demo_add",
    task_name="Demo Add",
    source="celery",
    record_result=True,
    success_message="Demo task completed",
)
def add(x: float, y: float) -> float:
    """Return the sum of two numbers."""
    return x + y

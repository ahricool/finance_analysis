# -*- coding: utf-8 -*-
"""Demo Celery tasks for integration smoke tests."""

from __future__ import annotations

from src.celery_app.app import celery_app


@celery_app.task(name="demo.add")
def add(x: float, y: float) -> float:
    """Return the sum of two numbers."""
    return x + y

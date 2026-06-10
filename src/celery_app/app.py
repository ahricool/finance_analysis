# -*- coding: utf-8 -*-
"""Celery application factory and shared instance."""

from __future__ import annotations

from celery import Celery

from src.config import get_config

CELERY_APP_NAME = "finance_analysis"


def create_celery_app() -> Celery:
    """Build a Celery app using the project Redis URL as broker and result backend."""
    config = get_config()
    app = Celery(
        CELERY_APP_NAME,
        broker=config.redis_url,
        backend=config.redis_url,
        include=["src.celery_app.tasks.demo"],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_track_started=True,
    )
    return app


celery_app = create_celery_app()

"""Celery application dedicated exclusively to the qlib queue."""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from qlib_worker.config import get_worker_config

QUEUE_QLIB = "qlib"
TASK_MODULES = (
    "qlib_worker.tasks.train",
    "qlib_worker.tasks.predict",
    "qlib_worker.tasks.artifact",
)


def create_celery_app() -> Celery:
    config = get_worker_config()
    app = Celery("finance_analysis_qlib", broker=config.redis_url, backend=config.redis_url, include=TASK_MODULES)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_default_queue=QUEUE_QLIB,
        task_queues=(Queue(QUEUE_QLIB),),
        task_routes={
            "qlib.model.train": {"queue": QUEUE_QLIB},
            "qlib.model.predict": {"queue": QUEUE_QLIB},
            "qlib.dataset.validate": {"queue": QUEUE_QLIB},
            "qlib.artifact.inspect": {"queue": QUEUE_QLIB},
        },
        task_track_started=True,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=1,
        enable_utc=True,
    )
    return app


celery_app = create_celery_app()

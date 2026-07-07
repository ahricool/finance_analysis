from __future__ import annotations

import os

os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from qlib_worker.celery_app import QUEUE_QLIB, celery_app  # noqa: E402


def test_qlib_worker_registers_only_qlib_queue() -> None:
    assert QUEUE_QLIB == "qlib"
    assert [queue.name for queue in celery_app.conf.task_queues] == ["qlib"]
    assert celery_app.conf.task_default_queue == "qlib"
    assert {route["queue"] for route in celery_app.conf.task_routes.values()} == {"qlib"}

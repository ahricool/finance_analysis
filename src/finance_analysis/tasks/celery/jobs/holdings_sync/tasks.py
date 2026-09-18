"""Periodic Google Sheet holdings snapshot publish on the ingestion queue."""

from __future__ import annotations

from typing import Any, Optional

from finance_analysis.holdings.service import HoldingsService  # pragma: allowlist secret
from finance_analysis.holdings.snapshot import SnapshotRejected  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.client import GoogleSheetsError  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.oauth import GoogleOAuthError  # pragma: allowlist secret
from finance_analysis.tasks.celery.app import celery_app  # pragma: allowlist secret
from finance_analysis.tasks.celery.schedule import JOB_HOLDINGS_SYNC, require_scheduled_task_definition  # pragma: allowlist secret
from finance_analysis.tasks.lifecycle import TaskSkipped, track_task  # pragma: allowlist secret

DEFINITION = require_scheduled_task_definition(JOB_HOLDINGS_SYNC)


@celery_app.task(
    name=DEFINITION.celery_task_name,
    time_limit=240,
    soft_time_limit=180,
    expires=DEFINITION.expires,
)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    success_message="Google Sheet 持仓同步完成",
    strip_lifecycle_kwargs=True,
)
def run_holdings_sync(
    scheduler_job_id: Optional[str] = None,
    uid: int | None = None,
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    service = HoldingsService()
    sources = [service.repository.get_for_uid(uid)] if uid is not None else service.repository.list_enabled()
    sources = [item for item in sources if item is not None and item.enabled]
    if not sources:
        raise TaskSkipped("没有已连接的 Google Sheet 持仓来源")
    changed = 0
    failed = 0
    rebuilt = 0
    for source in sources:
        try:
            result = service.sync(uid=source.uid)
        except (GoogleOAuthError, GoogleSheetsError, SnapshotRejected):
            failed += 1
            continue
        if result.get("changed"):
            changed += 1
        if result.get("cache_rebuilt"):
            rebuilt += 1
    return {
        "status": "completed",
        "sources": len(sources),
        "changed": changed,
        "cache_rebuilt": rebuilt,
        "failed": failed,
    }


__all__ = ["run_holdings_sync"]

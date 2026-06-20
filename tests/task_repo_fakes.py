from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, Optional

from finance_analysis.core.time import utc_now


class FakeTaskRecordRepository:
    ACTIVE_STATUSES = ("pending", "processing", "retrying")

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}

    def create_pending_or_get_duplicate(self, **kwargs):
        dedupe_key = kwargs.get("dedupe_key")
        existing = self.get_active_by_dedupe_key(dedupe_key)
        if existing is not None:
            return existing, False
        record = SimpleNamespace(
            id=len(self.records) + 1,
            task_id=kwargs["task_id"],
            task_type=kwargs["task_type"],
            task_name=kwargs.get("task_name"),
            uid=kwargs.get("uid"),
            source=kwargs["source"],
            trigger_source=kwargs.get("trigger_source"),
            triggered_by_uid=kwargs.get("triggered_by_uid"),
            status="pending",
            progress=kwargs.get("progress", 0),
            message=kwargs.get("message"),
            payload=kwargs.get("payload"),
            result=None,
            error=None,
            task_log=kwargs.get("task_log"),
            parent_task_id=kwargs.get("parent_task_id"),
            retry_count=kwargs.get("retry_count", 0),
            scheduler_job_id=kwargs.get("scheduler_job_id"),
            dedupe_key=dedupe_key,
            created_at=utc_now(),
            started_at=None,
            finished_at=None,
            updated_at=utc_now(),
        )
        self.records[record.task_id] = record
        return record, True

    def get_active_by_dedupe_key(self, dedupe_key: Optional[str]):
        if not dedupe_key:
            return None
        for record in self.records.values():
            if record.dedupe_key == dedupe_key and record.status in self.ACTIVE_STATUSES:
                return record
        return None

    def get_by_task_id(self, task_id: str):
        return self.records.get(task_id)

    def list_tasks(self, *, statuses: Optional[Iterable[str]] = None, limit: int = 50, **_: Any):
        status_set = set(statuses or [])
        records = list(self.records.values())
        if status_set:
            records = [record for record in records if record.status in status_set]
        return sorted(records, key=lambda record: record.created_at, reverse=True)[:limit]

    def count_tasks(self, *, statuses: Optional[Iterable[str]] = None, **_: Any) -> int:
        return len(self.list_tasks(statuses=statuses, limit=10_000))

    def count_by_status(self, **_: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records.values():
            counts[record.status] = counts.get(record.status, 0) + 1
        return counts

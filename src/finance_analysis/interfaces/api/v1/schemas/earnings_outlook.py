"""Public detail envelope; versioned JSON payloads remain explicit extensible evidence."""

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field


class OutlookVersion(BaseModel):
    id: int
    stage: Literal["daily", "final", "manual"]
    applicability: Literal["valid", "superseded", "ineligible"]
    generated_at: datetime
    data_cutoff: datetime
    release_cutoff: datetime
    model: str | None
    backend: str | None
    prompt_version: str
    schedule_hash: str
    prediction: dict[str, Any]
    context: dict[str, Any]
    research: dict[str, Any]
    search_evidence: dict[str, Any]


class OutlookDetail(BaseModel):
    status: str
    error: str | None = None
    summary: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    versions: list[OutlookVersion] = Field(default_factory=list)


class OutlookTaskSubmitted(BaseModel):
    task_id: str
    event_id: int
    status: Literal["pending"] = "pending"

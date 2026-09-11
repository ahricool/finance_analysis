"""Message center responses. Delivery state is deliberately absent."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from finance_analysis.core.time import coerce_aware_utc


class NotificationPreview(BaseModel):
    id: int
    uid: Optional[int]
    title: str
    content_preview: str
    route_type: str
    severity: str
    created_at: datetime

    _utc = field_validator("created_at")(coerce_aware_utc)


class NotificationListResponse(BaseModel):
    items: list[NotificationPreview]
    total: int
    page: int
    page_size: int


class NotificationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    route_type: str
    severity: str
    created_at: datetime

    _utc = field_validator("created_at")(coerce_aware_utc)

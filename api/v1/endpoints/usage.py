# -*- coding: utf-8 -*-
"""LLM usage tracking endpoint."""

from __future__ import annotations

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from api.deps import get_database_manager, get_effective_uid
from api.v1.schemas.usage import UsageSummaryResponse
from src.storage import DatabaseManager
from src.time_utils import DEFAULT_DISPLAY_TIMEZONE

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_PERIODS = {"today", "month", "all"}


def _date_range(period: str):
    """Return aware UTC bounds for the requested period in the default display timezone."""
    tz = ZoneInfo(DEFAULT_DISPLAY_TIMEZONE)
    now = datetime.now(tz=tz)
    if period == "today":
        from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        from_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # all
        from_dt = datetime.combine(datetime(2000, 1, 1).date(), time.min, tzinfo=tz)
    return from_dt.astimezone(ZoneInfo("UTC")), now.astimezone(ZoneInfo("UTC"))


@router.get(
    "/summary",
    response_model=UsageSummaryResponse,
    summary="LLM token usage summary",
    description="Aggregate token consumption by period, call type, and model.",
)
def get_usage_summary(
    http_request: Request,
    period: str = Query("month", description="'today' | 'month' | 'all'"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> UsageSummaryResponse:
    if period not in _VALID_PERIODS:
        period = "month"

    from_dt, to_dt = _date_range(period)

    uid = get_effective_uid(http_request)
    data = db_manager.get_llm_usage_summary(from_dt, to_dt, uid=uid)

    return UsageSummaryResponse(
        period=period,
        from_date=from_dt.date().isoformat(),
        to_date=to_dt.date().isoformat(),
        total_calls=data["total_calls"],
        total_tokens=data["total_tokens"],
        by_call_type=data["by_call_type"],
        by_model=data["by_model"],
    )

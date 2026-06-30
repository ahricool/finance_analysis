"""Read-only signal evaluation endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.signal import SignalRepository
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.signals import (
    SignalDirection,
    SignalListResponse,
    SignalResponse,
)

router = APIRouter()
Market = Literal["CN", "US", "HK"]


def _repo() -> SignalRepository:
    return SignalRepository()


def _validate_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise HTTPException(status_code=422, detail=f"{field_name} must include timezone information")


@router.get("", response_model=SignalListResponse, summary="查询信号评估列表")
def list_signals(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    market: Optional[Market] = None,
    direction: Optional[SignalDirection] = None,
    signal_type: Optional[str] = None,
    keyword: Optional[str] = None,
    signal_at_from: Optional[datetime] = None,
    signal_at_to: Optional[datetime] = None,
    _: User = Depends(require_current_user),
) -> SignalListResponse:
    _validate_aware(signal_at_from, "signal_at_from")
    _validate_aware(signal_at_to, "signal_at_to")
    repository = _repo()
    query = {
        "market": market,
        "direction": direction,
        "signal_type": signal_type,
        "keyword": keyword,
        "signal_at_from": signal_at_from,
        "signal_at_to": signal_at_to,
    }
    items = repository.list_signals(
        limit=page_size,
        offset=(page - 1) * page_size,
        **query,
    )
    return SignalListResponse(
        items=[SignalResponse.model_validate(item) for item in items],
        total=repository.count_signals(**query),
        page=page,
        page_size=page_size,
    )


@router.get("/{signal_id}", response_model=SignalResponse, summary="查询信号评估详情")
def get_signal(signal_id: int, _: User = Depends(require_current_user)) -> SignalResponse:
    item = _repo().get_by_id(signal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return SignalResponse.model_validate(item)


__all__ = ["get_signal", "list_signals", "router"]

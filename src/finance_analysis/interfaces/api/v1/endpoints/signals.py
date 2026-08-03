"""Read-only signal evaluation endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.signal import SignalRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
from finance_analysis.integrations.market_data.normalizer import canonical_symbol
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


def _signal_responses(repository: SignalRepository, items) -> list[SignalResponse]:
    canonical_codes = [canonical_symbol(item.code, item.market) for item in items]
    names = (
        MarketDataSymbolRepository(repository.db).names_by_codes(canonical_codes)
        if getattr(repository, "db", None) is not None
        else {}
    )
    return [
        SignalResponse.model_validate(item).model_copy(
            update={"name": names.get(code) or item.name}
        )
        for item, code in zip(items, canonical_codes)
    ]


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
        items=_signal_responses(repository, items),
        total=repository.count_signals(**query),
        page=page,
        page_size=page_size,
    )


@router.get("/{signal_id}", response_model=SignalResponse, summary="查询信号评估详情")
def get_signal(signal_id: int, _: User = Depends(require_current_user)) -> SignalResponse:
    repository = _repo()
    item = repository.get_by_id(signal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return _signal_responses(repository, [item])[0]


__all__ = ["get_signal", "list_signals", "router"]

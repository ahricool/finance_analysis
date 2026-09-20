"""Authenticated, database-only BTC strategy reads."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.crypto.service import CryptoService
from finance_analysis.interfaces.api.v1.schemas.crypto import (
    CryptoOverviewResponse,
    CryptoPerformanceResponse,
    CryptoSignalsResponse,
)

router = APIRouter()


def get_crypto_service():
    return CryptoService()


@router.get("/btc/overview", response_model=CryptoOverviewResponse)
def overview(service: CryptoService = Depends(get_crypto_service)):
    return service.get_overview()


@router.get("/btc/signals", response_model=CryptoSignalsResponse)
def signals(
    limit: int = Query(50, ge=1, le=200),
    start: datetime | None = None,
    end: datetime | None = None,
    actions_only: bool = False,
    service: CryptoService = Depends(get_crypto_service),
):
    if (start is None) != (end is None) or (start and (not start.tzinfo or not end.tzinfo or start > end)):
        raise HTTPException(422, "Supply an ordered, timezone-aware start/end pair")
    return {
        "items": service.get_signals(
            None if start and actions_only else limit, start=start, end=end, actions_only=actions_only
        )
    }


@router.get("/btc/performance", response_model=CryptoPerformanceResponse)
def performance(service: CryptoService = Depends(get_crypto_service)):
    return service.get_performance()

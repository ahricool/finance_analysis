"""Authenticated, database-only BTC strategy reads."""

from fastapi import APIRouter, Depends, Query

from finance_analysis.crypto.service import CryptoService
from finance_analysis.interfaces.api.v1.schemas.crypto import CryptoOverviewResponse, CryptoSignalsResponse

router = APIRouter()


def get_crypto_service():
    return CryptoService()


@router.get("/btc/overview", response_model=CryptoOverviewResponse)
def overview(service: CryptoService = Depends(get_crypto_service)):
    return service.get_overview()


@router.get("/btc/signals", response_model=CryptoSignalsResponse)
def signals(limit: int = Query(50, ge=1, le=200), service: CryptoService = Depends(get_crypto_service)):
    return {"items": service.get_signals(limit)}

"""Authenticated, database-only BTC strategy reads."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.crypto.registry import BREAKOUT_KEY, SYMBOL
from finance_analysis.crypto.service import CryptoService
from finance_analysis.interfaces.api.v1.schemas.crypto import (
    CryptoOverviewResponse,
    CryptoPerformanceResponse,
    CryptoPerformanceSummary,
    CryptoSignalsResponse,
    CryptoStrategyResponse,
)

router = APIRouter()


def get_crypto_service():
    return CryptoService()


def require_strategy(service, strategy_key):
    if service.definition(strategy_key) is None:
        raise HTTPException(404, "Unknown BTC strategy")


@router.get("/btc/strategies", response_model=list[CryptoStrategyResponse])
def strategies(service: CryptoService = Depends(get_crypto_service)):
    return service.get_strategies()


@router.get("/btc/strategies/performance", response_model=list[CryptoPerformanceSummary])
def performance_summaries(service: CryptoService = Depends(get_crypto_service)):
    return [service.get_performance(item.key, SYMBOL) for item in service.definitions if item.enabled]


@router.get("/btc/overview", response_model=CryptoOverviewResponse)
@router.get("/btc/strategies/{strategy_key}/overview", response_model=CryptoOverviewResponse)
def overview(strategy_key: str = BREAKOUT_KEY, service: CryptoService = Depends(get_crypto_service)):
    require_strategy(service, strategy_key)
    return service.get_overview(strategy_key, SYMBOL)


@router.get("/btc/signals", response_model=CryptoSignalsResponse)
@router.get("/btc/strategies/{strategy_key}/signals", response_model=CryptoSignalsResponse)
def signals(
    strategy_key: str = BREAKOUT_KEY,
    limit: int = Query(50, ge=1, le=2000),
    start: datetime | None = None,
    end: datetime | None = None,
    actions_only: bool = False,
    service: CryptoService = Depends(get_crypto_service),
):
    require_strategy(service, strategy_key)
    if (start is None) != (end is None) or (start and (not start.tzinfo or not end.tzinfo or start > end)):
        raise HTTPException(422, "Supply an ordered, timezone-aware start/end pair")
    return {"items": service.get_signals(strategy_key, SYMBOL, limit, start=start, end=end, actions_only=actions_only)}


@router.get("/btc/performance", response_model=CryptoPerformanceResponse)
@router.get("/btc/strategies/{strategy_key}/performance", response_model=CryptoPerformanceResponse)
def performance(strategy_key: str = BREAKOUT_KEY, service: CryptoService = Depends(get_crypto_service)):
    require_strategy(service, strategy_key)
    return service.get_performance(strategy_key, SYMBOL)

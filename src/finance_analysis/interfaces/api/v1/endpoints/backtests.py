"""Authenticated API for daily strategy backtests."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from finance_analysis.backtest.engines.registry import get_engine_definition, get_engine_definitions
from finance_analysis.backtest.service import BacktestService
from finance_analysis.backtest.strategies.registry import list_strategies
from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.backtest import BacktestRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.backtests import (
    BacktestConfigRequest,
    BacktestEquityListResponse,
    BacktestRunCreate,
    BacktestRunListResponse,
    BacktestRunResponse,
    BacktestTradeListResponse,
    EngineResponse,
    PreflightResponse,
    StrategyResponse,
    SymbolResponse,
)

router = APIRouter()


@router.get("/engines", response_model=list[EngineResponse])
async def engines(_: User = Depends(require_current_user)):
    return [asdict(item) for item in get_engine_definitions()]


@router.get("/strategies", response_model=list[StrategyResponse])
async def strategies(
    engine: str | None = None,
    market: str | None = None,
    _: User = Depends(require_current_user),
):
    engine = engine.lower() if engine else None
    market = market.upper() if market else None
    if engine:
        definition = get_engine_definition(engine)
        if market and market not in definition.supported_markets:
            return []
    return [asdict(item) for item in list_strategies(engine=engine, market=market)]


@router.get("/symbols", response_model=list[SymbolResponse])
async def symbols(
    market: str,
    keyword: str = "",
    engine: str = "backtrader",
    _: User = Depends(require_current_user),
):
    definition = get_engine_definition(engine.lower())
    market = market.upper()
    if not definition.available or market not in definition.supported_markets:
        return []
    return MarketDataSymbolRepository().search_enabled_symbols(market, keyword, limit=30)


@router.post("/preflight", response_model=PreflightResponse)
async def preflight(body: BacktestConfigRequest, _: User = Depends(require_current_user)):
    try:
        return asdict(BacktestService().preflight(body.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs", response_model=BacktestRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(body: BacktestRunCreate, user: User = Depends(require_current_user)):
    try:
        return BacktestService().create_run(user.id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs", response_model=BacktestRunListResponse)
async def runs(
    engine: str | None = None,
    strategy_key: str | None = None,
    market: str | None = None,
    code: str | None = None,
    status_value: str | None = Query(None, alias="status"),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    uid: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_current_user),
):
    items, total = BacktestRepository().list_runs(
        uid=user.id,
        is_admin=user.role == "admin",
        page=page,
        page_size=page_size,
        filters={
            "engine": engine,
            "strategy_key": strategy_key,
            "market": market.upper() if market else None,
            "code": code.upper() if code else None,
            "status": status_value,
            "created_from": created_from,
            "created_to": created_to,
            "uid": uid,
        },
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/runs/{run_id}", response_model=BacktestRunResponse)
async def run_detail(run_id: int, user: User = Depends(require_current_user)):
    run = BacktestRepository().get_run(run_id, uid=user.id, is_admin=user.role == "admin")
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return run


@router.get("/runs/{run_id}/trades", response_model=BacktestTradeListResponse)
async def run_trades(
    run_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    user: User = Depends(require_current_user),
):
    result = BacktestRepository().list_trades(
        run_id, uid=user.id, is_admin=user.role == "admin", page=page, page_size=page_size
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    items, total = result
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/runs/{run_id}/equity", response_model=BacktestEquityListResponse)
async def run_equity(run_id: int, user: User = Depends(require_current_user)):
    items = BacktestRepository().list_equity(run_id, uid=user.id, is_admin=user.role == "admin")
    if items is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return {"items": items}


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: int, user: User = Depends(require_current_user)):
    deleted = BacktestRepository().delete_run(run_id, uid=user.id, is_admin=user.role == "admin")
    if not deleted:
        raise HTTPException(status_code=409, detail="Run not found or still processing")

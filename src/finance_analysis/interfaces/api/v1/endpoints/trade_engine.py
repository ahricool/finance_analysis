# -*- coding: utf-8 -*-
"""Trade Engine read/run API. Advice only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from finance_analysis.interfaces.api.deps import get_effective_uid, require_admin, require_current_user  # pragma: allowlist secret
from finance_analysis.trade_engine.service import TradeEngineService  # pragma: allowlist secret

router = APIRouter(dependencies=[Depends(require_current_user)])
NO_STORE = {"Cache-Control": "private, no-store"}


def _service() -> TradeEngineService:
    return TradeEngineService()


def _private(response: Response) -> None:
    response.headers.update(NO_STORE)


@router.get("/positions")
def positions(
    request: Request,
    response: Response,
    market: str | None = None,
    service: TradeEngineService = Depends(_service),
):
    _private(response)
    return {"items": service.list_position_views(get_effective_uid(request), market=market)}


@router.get("/signals")
def signals(
    request: Request,
    response: Response,
    market: str | None = None,
    position_id: str | None = None,
    service: TradeEngineService = Depends(_service),
):
    _private(response)
    return {"items": service.list_signals(get_effective_uid(request), market=market, position_id=position_id)}


@router.get("/strategies")
def strategies(response: Response, market: str = Query("CN"), service: TradeEngineService = Depends(_service)):
    _private(response)
    return {"items": service.list_strategies(market.upper())}


@router.post("/run")
def run(
    request: Request,
    response: Response,
    market: str = Query("CN"),
    service: TradeEngineService = Depends(_service),
    _admin=Depends(require_admin),
):
    _private(response)
    uid = get_effective_uid(request)
    return service.evaluate_uid(uid, market=market.upper())

# -*- coding: utf-8 -*-
"""Private holdings API: DB portfolio is the only holdings fact source."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from finance_analysis.interfaces.api.deps import get_effective_uid, require_current_user  # pragma: allowlist secret
from finance_analysis.interfaces.api.v1.schemas.holdings import (  # pragma: allowlist secret
    CashRequest,
    TradeRequest,
)
from finance_analysis.portfolio.context import render_portfolio_context  # pragma: allowlist secret
from finance_analysis.portfolio.errors import OperationConflictError, PortfolioError  # pragma: allowlist secret
from finance_analysis.portfolio.markers import markers_from_operations  # pragma: allowlist secret
from finance_analysis.portfolio.resolver import PortfolioResolver  # pragma: allowlist secret
from finance_analysis.portfolio.service import PortfolioService  # pragma: allowlist secret
from finance_analysis.portfolio.valuation import portfolio_summary
from finance_analysis.portfolio.views import _account_payload, _json_dec, _position_payload

router = APIRouter(dependencies=[Depends(require_current_user)])
NO_STORE = {"Cache-Control": "private, no-store"}


def _portfolio() -> PortfolioService:
    return PortfolioService()


def _resolver() -> PortfolioResolver:
    return PortfolioResolver()


def _private(response: Response) -> None:
    response.headers.update(NO_STORE)


@router.get("/summary")
def summary(
    request: Request,
    response: Response,
    market: str = Query("CN", pattern="^(CN|US)$"),
    service: PortfolioService = Depends(_portfolio),
):
    _private(response)
    return portfolio_summary(get_effective_uid(request), market, service=service)


@router.get("/positions")
def list_positions(
    request: Request,
    response: Response,
    market: str | None = None,
    service: PortfolioService = Depends(_portfolio),
):
    _private(response)
    return {"items": [_position_payload(item) for item in service.list_positions(get_effective_uid(request), market=market)]}


@router.get("/positions/{position_id}")
def get_position(position_id: int, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    row = service.get_position(get_effective_uid(request), position_id)
    if row is None:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return _position_payload(row)


@router.post("/buy")
def buy(body: TradeRequest, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    if not body.account_id or not body.symbol:
        raise HTTPException(status_code=400, detail="买入需要账户和代码")
    try:
        return _position_payload(
            service.buy(
                get_effective_uid(request),
                account_id=body.account_id,
                symbol=body.symbol,
                quantity=body.quantity,
                price=body.price,
                executed_at=body.executed_at,
                note=body.note,
                operation_id=str(body.operation_id),
                asset_type=body.asset_type or "STOCK",
            )
        )
    except PortfolioError as extra:
        raise HTTPException(status_code=409 if isinstance(extra, OperationConflictError) else 400, detail=str(extra)) from extra


@router.post("/sell")
def sell(body: TradeRequest, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    if not body.position_id:
        raise HTTPException(status_code=400, detail="卖出需要持仓")
    try:
        return _position_payload(
            service.sell(
                get_effective_uid(request),
                position_id=body.position_id,
                quantity=body.quantity,
                price=body.price,
                executed_at=body.executed_at,
                note=body.note,
                operation_id=str(body.operation_id),
            )
        )
    except PortfolioError as extra:
        raise HTTPException(status_code=409 if isinstance(extra, OperationConflictError) else 400, detail=str(extra)) from extra


@router.patch("/cash")
def set_cash(body: CashRequest, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    try:
        return _account_payload(
            service.set_cash(get_effective_uid(request), account_id=body.account_id, amount=body.amount,
                             operation_id=str(body.operation_id))
        )
    except PortfolioError as extra:
        raise HTTPException(status_code=409 if isinstance(extra, OperationConflictError) else 400, detail=str(extra)) from extra


@router.get("/positions/{position_id}/operations")
def operations(position_id: int, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    try:
        rows = service.list_operations(get_effective_uid(request), position_id)
    except PortfolioError as extra:
        raise HTTPException(status_code=404, detail=str(extra)) from extra
    return {
        "items": [
            {
                "id": row["id"],
                "side": row["side"],
                "quantity": _json_dec(row["quantity"]),
                "price": _json_dec(row["price"]),
                "executed_at": row["executed_at"],
                "note": row["note"],
            }
            for row in rows
        ]
    }


@router.get("/positions/{position_id}/markers")
def markers(position_id: int, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    uid = get_effective_uid(request)
    position = service.get_position(uid, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="持仓不存在")
    rows = service.list_operations(uid, position_id)
    payload = markers_from_operations(rows, market=position["market"])
    return {
        "items": [
            {
                "timestamp": item.timestamp.isoformat(),
                "type": item.type,
                "operations": [
                    {
                        "executed_at": op.executed_at.isoformat(),
                        "side": op.side,
                        "quantity": format(op.quantity, "f"),
                        "price": format(op.price, "f"),
                    }
                    for op in item.operations
                ],
            }
            for item in payload
        ]
    }


@router.get("/resolved")
def resolved(request: Request, response: Response, market: str | None = None, resolver: PortfolioResolver = Depends(_resolver)):
    _private(response)
    portfolio = resolver.get_resolved_portfolio(get_effective_uid(request), market=market)
    return {
        "text": render_portfolio_context(portfolio),
        "positions": [
            {
                "source": item.source,
                "coverage": item.coverage,
                "symbol": item.symbol,
                "quantity": format(item.quantity, "f"),
                "average_cost": format(item.average_cost, "f"),
                "asset_type": item.asset_type,
                "market": item.market,
            }
            for item in portfolio.positions
        ],
    }


@router.get("/context")
def context(request: Request, response: Response, resolver: PortfolioResolver = Depends(_resolver)):
    _private(response)
    return {"text": render_portfolio_context(resolver.get_resolved_portfolio(get_effective_uid(request)))}

# -*- coding: utf-8 -*-
"""Private holdings API: DB portfolio primary, Google Sheet secondary."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from finance_analysis.holdings.service import HoldingsService  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.oauth import GoogleOAuthError  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.spreadsheet import SpreadsheetIdError  # pragma: allowlist secret
from finance_analysis.interfaces.api.deps import get_effective_uid, require_current_user  # pragma: allowlist secret
from finance_analysis.interfaces.api.v1.schemas.holdings import (  # pragma: allowlist secret
    CashRequest,
    HoldingsConnectRequest,
    HoldingsConnectResponse,
    HoldingsDisconnectResponse,
    HoldingsPolicyUpdate,
    HoldingsSourceResponse,
    HoldingsSyncResponse,
    PositionUpdateRequest,
    TradeRequest,
)
from finance_analysis.portfolio.context import render_portfolio_context  # pragma: allowlist secret
from finance_analysis.portfolio.errors import PortfolioError  # pragma: allowlist secret
from finance_analysis.portfolio.markers import markers_from_operations  # pragma: allowlist secret
from finance_analysis.portfolio.resolver import PortfolioResolver  # pragma: allowlist secret
from finance_analysis.portfolio.service import PortfolioService  # pragma: allowlist secret
from finance_analysis.trade_engine.market import RiskMarketGateway  # pragma: allowlist secret

router = APIRouter(dependencies=[Depends(require_current_user)])
NO_STORE = {"Cache-Control": "private, no-store"}


def _holdings() -> HoldingsService:
    return HoldingsService()


def _portfolio() -> PortfolioService:
    return PortfolioService()


def _resolver() -> PortfolioResolver:
    return PortfolioResolver()


def _private(response: Response) -> None:
    response.headers.update(NO_STORE)


def _json_dec(value) -> str | None:
    if value is None:
        return None
    return format(value, "f")


@router.get("/summary")
def summary(
    request: Request,
    response: Response,
    market: str = Query("CN"),
    service: PortfolioService = Depends(_portfolio),
):
    _private(response)
    uid = get_effective_uid(request)
    market = market.upper()
    accounts = service.list_accounts(uid, market=market)
    positions = service.list_positions(uid, market=market)
    quotes = {}
    try:
        quotes = RiskMarketGateway().quotes([item["symbol"] for item in positions])
    except Exception:
        quotes = {}
    cash = sum((item["cash"] for item in accounts), start=Decimal("0"))
    market_value = Decimal("0")
    priced = []
    for item in positions:
        quote = quotes.get(item["symbol"])
        price = quote.price if quote is not None and quote.valid and not quote.stale else None
        value = None if price is None else item["quantity"] * price
        if value is not None:
            market_value += value
        pnl = None if price is None else (price - item["average_cost"]) * item["quantity"]
        priced.append({**_position_payload(item), "current_price": _json_dec(price), "market_value": _json_dec(value), "unrealized_pnl": _json_dec(pnl)})
    total = cash + market_value
    for item in priced:
        weight = None
        if total > 0 and item["market_value"] is not None:
            weight = format(Decimal(item["market_value"]) / total, "f")
        item["weight"] = weight
    return {
        "market": market,
        "accounts": [_account_payload(item) for item in accounts],
        "cash": _json_dec(cash),
        "market_value": _json_dec(market_value),
        "total_asset": _json_dec(total),
        "gross_exposure": None if total <= 0 else format(market_value / total, "f"),
        "positions": priced,
    }


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


@router.patch("/positions/{position_id}")
def patch_position(
    position_id: int,
    body: PositionUpdateRequest,
    request: Request,
    response: Response,
    service: PortfolioService = Depends(_portfolio),
):
    _private(response)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    try:
        return _position_payload(
            service.update_position(
                get_effective_uid(request),
                position_id,
                trade_engine_enabled=payload.get("trade_engine_enabled"),
            )
        )
    except PortfolioError as exc:
        status = 404 if str(exc) == "持仓不存在" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


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
                asset_type=body.asset_type or "STOCK",
            )
        )
    except PortfolioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
            )
        )
    except PortfolioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cash/deposit")
def deposit(body: CashRequest, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    try:
        return _account_payload(
            service.deposit(
                get_effective_uid(request),
                account_id=body.account_id,
                amount=body.amount,
                executed_at=body.executed_at,
                note=body.note,
            )
        )
    except PortfolioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cash/withdraw")
def withdraw(body: CashRequest, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    try:
        return _account_payload(
            service.withdraw(
                get_effective_uid(request),
                account_id=body.account_id,
                amount=body.amount,
                executed_at=body.executed_at,
                note=body.note,
            )
        )
    except PortfolioError as extra:
        raise HTTPException(status_code=400, detail=str(extra)) from extra


@router.get("/positions/{position_id}/operations")
def operations(position_id: int, request: Request, response: Response, service: PortfolioService = Depends(_portfolio)):
    _private(response)
    try:
        rows = service.list_operations(get_effective_uid(request), position_id)
    except PortfolioError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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


def _google_source(request: Request, response: Response, service: HoldingsService = Depends(_holdings)):
    _private(response)
    return service.public_source(get_effective_uid(request))


def _google_connect(
    request: Request,
    body: HoldingsConnectRequest,
    response: Response,
    service: HoldingsService = Depends(_holdings),
):
    _private(response)
    try:
        return service.connect(
            uid=get_effective_uid(request),
            spreadsheet_value=body.spreadsheet_id,
            return_path=body.return_path,
        )
    except SpreadsheetIdError as extra:
        raise HTTPException(status_code=400, detail=str(extra)) from extra
    except GoogleOAuthError as extra:
        raise HTTPException(status_code=400, detail=extra.message) from extra


def _google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    service: HoldingsService = Depends(_holdings),
):
    uid = get_effective_uid(request)
    if error:
        raise HTTPException(status_code=400, detail="Google 授权被拒绝，请重新连接")
    try:
        result = service.callback(uid=uid, code=code or "", state=state or "")
    except GoogleOAuthError as extra:
        raise HTTPException(status_code=400, detail=extra.message) from extra
    return RedirectResponse(url=f"{result['return_path']}?google={result['auth_status']}", status_code=302)


def _google_disconnect(request: Request, response: Response, service: HoldingsService = Depends(_holdings)):
    _private(response)
    return service.disconnect(uid=get_effective_uid(request))


def _google_sync(request: Request, response: Response, service: HoldingsService = Depends(_holdings)):
    _private(response)
    uid = get_effective_uid(request)
    try:
        from finance_analysis.tasks.celery.app import celery_app  # pragma: allowlist secret

        task = celery_app.send_task(
            "scheduled.holdings_sync",
            kwargs={"uid": uid, "_trigger_source": "manual", "_triggered_by_uid": uid},
            queue="ingestion",
        )
        return {"task_id": task.id, "status": "queued"}
    except Exception:
        result = service.sync(uid=uid)
        return {"task_id": None, "changed": result["changed"], "generation": result["generation"], "status": "ok"}


router.add_api_route("/google/source", _google_source, methods=["GET"], response_model=HoldingsSourceResponse)
router.add_api_route("/source", _google_source, methods=["GET"], response_model=HoldingsSourceResponse)
router.add_api_route("/google/connect", _google_connect, methods=["POST"], response_model=HoldingsConnectResponse)
router.add_api_route("/connect", _google_connect, methods=["POST"], response_model=HoldingsConnectResponse)
router.add_api_route("/google/oauth/callback", _google_callback, methods=["GET"])
router.add_api_route("/oauth/callback", _google_callback, methods=["GET"])
router.add_api_route("/google/disconnect", _google_disconnect, methods=["POST"], response_model=HoldingsDisconnectResponse)
router.add_api_route("/disconnect", _google_disconnect, methods=["POST"], response_model=HoldingsDisconnectResponse)
router.add_api_route("/google/sync", _google_sync, methods=["POST"], response_model=HoldingsSyncResponse)
router.add_api_route("/sync", _google_sync, methods=["POST"], response_model=HoldingsSyncResponse)


@router.get("/snapshot")
def snapshot(request: Request, response: Response, service: HoldingsService = Depends(_holdings)):
    _private(response)
    current = service.get_snapshot(uid=get_effective_uid(request))
    if current is None:
        return {"status": "UNAVAILABLE", "snapshot": None}
    return {"status": current.status, "snapshot": current.model_dump(mode="json")}


@router.get("/context")
def context(request: Request, response: Response, resolver: PortfolioResolver = Depends(_resolver)):
    _private(response)
    return {"text": render_portfolio_context(resolver.get_resolved_portfolio(get_effective_uid(request)))}


@router.get("/policy")
def get_policy(request: Request, response: Response, service: HoldingsService = Depends(_holdings)):
    _private(response)
    source = service.repository.get_for_uid(get_effective_uid(request))
    return {"policy": {} if source is None else source.risk_policy, "policy_version": 1 if source is None else source.policy_version}


@router.put("/policy")
def put_policy(
    request: Request,
    body: HoldingsPolicyUpdate,
    response: Response,
    service: HoldingsService = Depends(_holdings),
):
    _private(response)
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    return service.update_policy(uid=get_effective_uid(request), policy=payload)


def _account_payload(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "market": item["market"],
        "cash": _json_dec(item["cash"]),
        "currency": item["currency"],
    }


def _position_payload(item: dict) -> dict:
    return {
        "id": item["id"],
        "account_id": item["account_id"],
        "market": item["market"],
        "symbol": item["symbol"],
        "asset_type": item["asset_type"],
        "quantity": _json_dec(item["quantity"]),
        "average_cost": _json_dec(item["average_cost"]),
        "trade_engine_enabled": True if item.get("trade_engine_enabled") is None else bool(item.get("trade_engine_enabled")),
        "opened_at": item.get("opened_at"),
        "closed_at": item.get("closed_at"),
        "lots": [
            {
                "id": lot["id"],
                "role": lot["role"],
                "entry_price": _json_dec(lot["entry_price"]),
                "remaining_quantity": _json_dec(lot["remaining_quantity"]),
                "entry_time": lot["entry_time"],
            }
            for lot in item.get("lots") or []
        ],
    }

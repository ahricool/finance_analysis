"""Authenticated APIs for fixed portfolio accounts, cash, and positions."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from finance_analysis.interfaces.api.deps import get_effective_uid
from finance_analysis.interfaces.api.v1.schemas.portfolio import (
    CashBalanceUpdate,
    EquityPositionCreate,
    OptionPositionCreate,
    PortfolioAccountResponse,
    PositionResponse,
    PositionUpdate,
)
from finance_analysis.portfolio.service import (
    PortfolioConflictError,
    PortfolioNotFoundError,
    PortfolioService,
    PortfolioValidationError,
)


router = APIRouter()


def _service() -> PortfolioService:
    return PortfolioService()


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, PortfolioNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PortfolioConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, PortfolioValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("/accounts", response_model=list[PortfolioAccountResponse])
def list_accounts(http_request: Request):
    uid = get_effective_uid(http_request)
    service = _service()
    accounts = service.ensure_fixed_portfolio_accounts(uid)
    return [PortfolioAccountResponse.model_validate(service.account_payload(item)) for item in accounts]


@router.get("/accounts/{account_id}", response_model=PortfolioAccountResponse)
def get_account(http_request: Request, account_id: int):
    uid = get_effective_uid(http_request)
    service = _service()
    try:
        account = service.get_account(uid, account_id)
    except Exception as exc:
        _raise_http(exc)
    return PortfolioAccountResponse.model_validate(service.account_payload(account))


@router.put("/accounts/{account_id}/cash", response_model=PortfolioAccountResponse)
def update_cash(http_request: Request, account_id: int, body: CashBalanceUpdate):
    uid = get_effective_uid(http_request)
    service = _service()
    try:
        account = service.set_cash_balance(uid, account_id, body.balance)
    except Exception as exc:
        _raise_http(exc)
    return PortfolioAccountResponse.model_validate(service.account_payload(account))


@router.get("/accounts/{account_id}/positions", response_model=list[PositionResponse])
def list_positions(
    http_request: Request,
    account_id: int,
    status_filter: Literal["OPEN", "CLOSED", "EXPIRED", "ALL"] = Query("OPEN", alias="status"),
    asset_type: Literal["STOCK", "ETF", "OPTION", "ALL"] = "ALL",
):
    uid = get_effective_uid(http_request)
    service = _service()
    try:
        positions = service.list_positions(
            uid, account_id, status=status_filter, asset_type=asset_type
        )
    except Exception as exc:
        _raise_http(exc)
    return [PositionResponse.model_validate(service.position_payload(item)) for item in positions]


@router.post(
    "/accounts/{account_id}/positions/equities",
    response_model=PositionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_equity_position(http_request: Request, account_id: int, body: EquityPositionCreate):
    uid = get_effective_uid(http_request)
    service = _service()
    try:
        position = service.create_equity_position(uid, account_id, **body.model_dump())
    except Exception as exc:
        _raise_http(exc)
    return PositionResponse.model_validate(service.position_payload(position))


@router.post(
    "/accounts/{account_id}/positions/options",
    response_model=PositionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_option_position(http_request: Request, account_id: int, body: OptionPositionCreate):
    uid = get_effective_uid(http_request)
    service = _service()
    try:
        position = service.create_option_position(uid, account_id, **body.model_dump())
    except Exception as exc:
        _raise_http(exc)
    return PositionResponse.model_validate(service.position_payload(position))


@router.put("/positions/{position_id}", response_model=PositionResponse)
def update_position(http_request: Request, position_id: int, body: PositionUpdate):
    uid = get_effective_uid(http_request)
    service = _service()
    try:
        position = service.update_position(uid, position_id, **body.model_dump(exclude_unset=True))
    except Exception as exc:
        _raise_http(exc)
    return PositionResponse.model_validate(service.position_payload(position))


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position(http_request: Request, position_id: int) -> Response:
    uid = get_effective_uid(http_request)
    try:
        _service().delete_position(uid, position_id)
    except Exception as exc:
        _raise_http(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

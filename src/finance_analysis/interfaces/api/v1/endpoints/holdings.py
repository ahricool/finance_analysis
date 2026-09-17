# -*- coding: utf-8 -*-
"""Private holdings API. Session uid only; never accept client-supplied uid."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from finance_analysis.holdings.service import HoldingsService  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.oauth import GoogleOAuthError  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.spreadsheet import SpreadsheetIdError  # pragma: allowlist secret
from finance_analysis.interfaces.api.deps import get_effective_uid, require_current_user  # pragma: allowlist secret
from finance_analysis.interfaces.api.v1.schemas.holdings import (  # pragma: allowlist secret
    HoldingsConnectRequest,
    HoldingsConnectResponse,
    HoldingsDisconnectResponse,
    HoldingsPlanCancelRequest,
    HoldingsPolicyUpdate,
    HoldingsRebaseRequest,
    HoldingsSourceResponse,
    HoldingsSyncResponse,
)

router = APIRouter(dependencies=[Depends(require_current_user)])
NO_STORE = {"Cache-Control": "private, no-store"}


def _service() -> HoldingsService:
    return HoldingsService()


def _private(response: Response) -> None:
    response.headers.update(NO_STORE)


@router.get("/source", response_model=HoldingsSourceResponse)
def get_source(request: Request, response: Response, service: HoldingsService = Depends(_service)):
    _private(response)
    return service.public_source(get_effective_uid(request))


@router.post("/connect", response_model=HoldingsConnectResponse)
def connect(
    request: Request,
    body: HoldingsConnectRequest,
    response: Response,
    service: HoldingsService = Depends(_service),
):
    _private(response)
    try:
        return service.connect(
            uid=get_effective_uid(request),
            spreadsheet_value=body.spreadsheet_id,
            return_path=body.return_path,
        )
    except SpreadsheetIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get("/oauth/callback")
def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    service: HoldingsService = Depends(_service),
):
    uid = get_effective_uid(request)
    if error:
        raise HTTPException(status_code=400, detail="Google 授权被拒绝，请重新连接")
    try:
        result = service.callback(uid=uid, code=code or "", state=state or "")
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    target = result["return_path"]
    status = result["auth_status"]
    return RedirectResponse(url=f"{target}?google={status}", status_code=302)


@router.post("/disconnect", response_model=HoldingsDisconnectResponse)
def disconnect(request: Request, response: Response, service: HoldingsService = Depends(_service)):
    _private(response)
    return service.disconnect(uid=get_effective_uid(request))


@router.post("/sync", response_model=HoldingsSyncResponse)
def sync_now(request: Request, response: Response, service: HoldingsService = Depends(_service)):
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
        return {
            "task_id": None,
            "changed": result["changed"],
            "generation": result["generation"],
            "status": "ok",
        }


@router.get("/snapshot")
def snapshot(request: Request, response: Response, service: HoldingsService = Depends(_service)):
    _private(response)
    current = service.get_snapshot(uid=get_effective_uid(request))
    if current is None:
        return {"status": "UNAVAILABLE", "snapshot": None}
    return {"status": current.status, "snapshot": current.model_dump(mode="json")}


@router.get("/context")
def context(request: Request, response: Response, service: HoldingsService = Depends(_service)):
    _private(response)
    text = service.get_context(uid=get_effective_uid(request))
    return {"text": text}


@router.get("/policy")
def get_policy(request: Request, response: Response, service: HoldingsService = Depends(_service)):
    _private(response)
    source = service.repository.get_for_uid(get_effective_uid(request))
    return {
        "policy": {} if source is None else source.risk_policy,
        "policy_version": 1 if source is None else source.policy_version,
    }


@router.put("/policy")
def put_policy(
    request: Request,
    body: HoldingsPolicyUpdate,
    response: Response,
    service: HoldingsService = Depends(_service),
):
    _private(response)
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    return service.update_policy(uid=get_effective_uid(request), policy=payload)


def _risk():
    from finance_analysis.portfolio_risk.service import PortfolioRiskService  # pragma: allowlist secret

    return PortfolioRiskService()


@router.get("/risk")
def get_risk(request: Request, response: Response, service=Depends(_risk)):
    _private(response)
    return service.latest_view(get_effective_uid(request))


@router.get("/events")
def get_events(request: Request, response: Response, service=Depends(_risk)):
    _private(response)
    view = service.latest_view(get_effective_uid(request))
    return {"events": view.get("events") or []}


@router.post("/risk/run")
def run_risk(request: Request, response: Response, service=Depends(_risk)):
    _private(response)
    return service.evaluate_uid(get_effective_uid(request))


@router.post("/plans/cancel")
def cancel_plan(
    request: Request,
    body: HoldingsPlanCancelRequest,
    response: Response,
    service=Depends(_risk),
):
    _private(response)
    try:
        return service.cancel_plan(
            uid=get_effective_uid(request),
            account_id=body.account_id,
            position_id=body.position_id,
            expected_state_version=body.expected_state_version,
            reason=body.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="position not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/legs/rebase")
def rebase_leg(
    request: Request,
    body: HoldingsRebaseRequest,
    response: Response,
    service=Depends(_risk),
):
    _private(response)
    try:
        return service.rebase(
            uid=get_effective_uid(request),
            account_id=body.account_id,
            position_id=body.position_id,
            leg_id=body.leg_id,
            expected_source_version=body.expected_source_version,
            expected_state_version=body.expected_state_version,
            reason=body.reason,
            observed_from=body.observed_from,
            high_watermark=body.high_watermark,
            profit_stage=body.profit_stage,
            active_stop=body.active_stop,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="leg not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

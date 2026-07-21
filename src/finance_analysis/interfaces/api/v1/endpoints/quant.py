"""Authenticated, explicitly market-scoped quant research API."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.quant import (
    DatasetBuildRequest,
    EventCreateRequest,
    EventImportRequest,
    IntradayRunRequest,
    ModelRunCreateRequest,
    PublishRequest,
)
from finance_analysis.quant.capabilities import get_quant_capabilities
from finance_analysis.quant.events.import_service import EventImportService
from finance_analysis.quant.models import QLIB_TRAINABLE_MODEL_KEYS
from finance_analysis.quant.price_modes import DEFAULT_QUANT_PRICE_MODE
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS

router = APIRouter()
QuantMarket = Literal["US", "CN"]
logger = logging.getLogger(__name__)


def encoded(value):
    return jsonable_encoder(value)


def _universe(repo: QuantRepository, market: str, key: str | None):
    try:
        return repo.supported_universe(market, key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/capabilities")
async def capabilities(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    return get_quant_capabilities(market)


@router.get("/universes")
async def universes(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    item = _universe(repo, market, None)
    members = repo.active_members(item.id, date.today())
    return [
        {
            **encoded(item),
            "member_count": len(members),
            "members": [
                {
                    "code": symbol.code,
                    "sector_key": member.sector_key,
                    "sector_benchmark_code": member.sector_benchmark_code,
                    "effective_from": member.effective_from,
                    "effective_to": member.effective_to,
                }
                for member, symbol in members
            ],
        }
    ]


@router.get("/models/definitions")
async def model_definitions(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    return encoded(
        [
            row
            for row in QuantRepository().list_model_definitions()
            if row.enabled
            and row.key in QLIB_TRAINABLE_MODEL_KEYS
            and market in (row.supported_markets or [])
        ]
    )


@router.get("/models")
async def models(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return encoded(repo.list_model_runs(market=market, universe_id=universe.id))


@router.get("/datasets")
async def datasets(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return encoded(repo.list_datasets(market=market, universe_id=universe.id))


@router.get("/datasets/{snapshot_id}")
async def dataset(snapshot_id: int, market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    row = repo.get_dataset(snapshot_id)
    if not row or row.market != market or row.universe_id != universe.id:
        raise HTTPException(404, "Dataset snapshot not found")
    return encoded(row)


@router.post("/datasets/build", status_code=status.HTTP_202_ACCEPTED)
async def build_dataset(body: DatasetBuildRequest, user: User = Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.quant_dataset.tasks import build_quant_dataset

    market = body.market.upper()
    universe = _universe(QuantRepository(), market, body.universe).key
    try:
        result = build_quant_dataset.apply_async(
            kwargs={
                "market": market,
                "universe": universe,
                "date_from": str(body.date_from),
                "date_to": str(body.date_to),
                "owner_uid": user.id,
            },
            queue=QUEUE_ANALYSIS,
        )
    except Exception as exc:
        logger.exception("Failed to submit quant dataset build task for market=%s", market)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Failed to submit quant dataset build task",
        ) from exc
    return {"task_id": result.id, "status": "pending", "market": market, "universe": universe}


@router.get("/market-regime/latest")
async def latest_market_regime(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    rows = QuantRepository().market_regimes(market, limit=1)
    if not rows:
        raise HTTPException(404, f"{market} market regime not available")
    return encoded(rows[0])


@router.get("/market-regime/history")
async def market_regime_history(
    market: QuantMarket = "US",
    date_from: date | None = None,
    date_to: date | None = None,
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    rows = QuantRepository().market_regimes(market, date_from, date_to)
    if model_version:
        rows = [row for row in rows if row.model_version == model_version]
    return encoded(rows)


@router.get("/sectors/ranking")
async def sector_ranking(
    market: QuantMarket = "US",
    trade_date: date | None = None,
    _: User = Depends(require_current_user),
):
    return encoded(QuantRepository().sector_regimes(market, trade_date))


@router.get("/sectors/{sector_key}")
async def sector_detail(
    sector_key: str,
    market: QuantMarket = "US",
    _: User = Depends(require_current_user),
):
    return encoded(QuantRepository().sector_regimes(market, sector_key=sector_key))


@router.get("/events")
async def events(
    market: QuantMarket = "US",
    code: str | None = None,
    event_type: str | None = None,
    direction: str | None = None,
    source: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: User = Depends(require_current_user),
):
    rows, total = QuantRepository().list_events(
        {
            "market": market,
            "code": code.upper() if code else None,
            "event_type": event_type,
            "direction": direction,
            "source": source,
            "published_from": published_from,
            "published_to": published_to,
        },
        (page - 1) * page_size,
        page_size,
    )
    return {"items": encoded(rows), "total": total, "page": page, "page_size": page_size, "market": market}


@router.get("/events/{event_id}")
async def event(event_id: int, market: QuantMarket = "US", _: User = Depends(require_current_user)):
    row = QuantRepository().get_event(event_id)
    if not row or row.market != market:
        raise HTTPException(404, "Event not found")
    return encoded(row)


@router.post("/events")
async def create_event(body: EventCreateRequest, _: User = Depends(require_admin)):
    result = EventImportService().import_json([body.model_dump()])
    if result["errors"]:
        raise HTTPException(400, result["errors"])
    return result


@router.post("/events/import")
async def import_events(body: EventImportRequest, _: User = Depends(require_admin)):
    if body.format == "json":
        return EventImportService().import_json(body.items)
    if body.format == "csv" and body.csv_content is not None:
        return EventImportService().import_csv(body.csv_content)
    raise HTTPException(400, "format must be json or csv with csv_content")


@router.post("/model-runs", status_code=status.HTTP_202_ACCEPTED)
async def create_model_run(body: ModelRunCreateRequest, user: User = Depends(require_admin)):
    repo = QuantRepository()
    market = body.market.upper()
    universe = _universe(repo, market, body.universe)
    definition = repo.get_model_definition(body.model_key)
    dataset = repo.get_dataset(body.dataset_snapshot_id)
    if (
        not definition
        or not definition.enabled
        or definition.key not in QLIB_TRAINABLE_MODEL_KEYS
        or not dataset
    ):
        raise HTTPException(400, "Unknown model or dataset")
    if market not in (definition.supported_markets or []):
        raise HTTPException(400, f"Model {body.model_key} does not support {market}")
    if dataset.market != market or dataset.universe_id != universe.id:
        raise HTTPException(409, "Model run, universe, and dataset market must match")
    if dataset.status != "ready":
        raise HTTPException(409, "Dataset is not ready")
    if dataset.price_mode != DEFAULT_QUANT_PRICE_MODE.value:
        raise HTTPException(
            409,
            f"Production training requires dataset price_mode={DEFAULT_QUANT_PRICE_MODE.value}",
        )
    values = body.model_dump(exclude={"universe"})
    values.update(
        {
            "market": market,
            "uid": user.id,
            "model_definition_id": definition.id,
            "universe_id": universe.id,
            "status": "draft",
            "progress": 0,
        }
    )
    run = repo.create_model_run(values)
    from finance_analysis.tasks.celery.jobs.quant_training.tasks import train_quant_model

    try:
        task = train_quant_model.apply_async(
            kwargs={"model_run_id": run.id, "owner_uid": user.id}, queue=QUEUE_ANALYSIS
        )
    except Exception as exc:
        logger.exception("Failed to submit model training task for model_run_id=%s", run.id)
        message = "Failed to submit model training task"
        repo.update_model_run(run.id, status="failed", progress=100, error=message)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, message) from exc
    repo.update_model_run(run.id, task_id=task.id)
    return {"model_run_id": run.id, "task_id": task.id, "status": "draft", "market": market}


@router.get("/model-runs")
async def model_runs(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return encoded(repo.list_model_runs(market=market, universe_id=universe.id))


@router.get("/model-runs/{run_id}")
async def model_run(run_id: int, market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    row = repo.get_model_run(run_id)
    if not row or row.market != market or row.universe_id != universe.id:
        raise HTTPException(404, "Model run not found")
    return encoded(row)


@router.post("/model-runs/{run_id}/publish")
async def publish_model(
    run_id: int,
    body: PublishRequest,
    market: QuantMarket = "US",
    user: User = Depends(require_admin),
):
    repo = QuantRepository()
    run = repo.get_model_run(run_id)
    if not run or run.market != market:
        raise HTTPException(404, "Model run not found")
    try:
        universe = repo.get_universe(run.universe_id)
        if not universe:
            raise ValueError(f"Model run {run_id} has no universe")
        _universe(repo, market, universe.key)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        return encoded(repo.publish_model(run_id, user.id, body.reason))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/signals/latest")
@router.get("/signals/ranking")
async def signals(
    market: QuantMarket = "US",
    universe: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    definition = _universe(repo, market, universe)
    rows = repo.latest_signals(market, definition.id)
    regimes = (
        repo.market_regimes(market, date_from=rows[0].trade_date, date_to=rows[0].trade_date, limit=1)
        if rows
        else []
    )
    return {
        "trade_date": rows[0].trade_date if rows else None,
        "market": market,
        "universe": definition.key,
        "market_regime": regimes[0].regime if regimes else None,
        "max_equity_exposure": regimes[0].max_equity_exposure if regimes else None,
        "items": encoded(rows),
    }


@router.get("/signals/{code}")
async def signal(code: str, market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    rows = repo.latest_signals(market, universe.id, code=code)
    if not rows:
        raise HTTPException(404, f"{market} signal not found")
    return encoded(rows[0])


@router.get("/signals/{code}/history")
async def signal_history(code: str, market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return encoded(repo.signal_history(market, code, universe.id))


@router.get("/portfolios/latest")
async def latest_portfolio(
    market: QuantMarket = "US",
    universe: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    definition = _universe(repo, market, universe)
    rows = repo.latest_portfolios(market, definition.id, 1)
    if not rows:
        raise HTTPException(404, f"{market} portfolio recommendation not found")
    result = repo.portfolio(rows[0].id, market, definition.id)
    if not result:
        raise HTTPException(404, "Portfolio recommendation not found")
    row, items = result
    return {**encoded(row), "universe": definition.key, "items": encoded(items)}


@router.get("/portfolios")
async def portfolios(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return encoded(repo.latest_portfolios(market, universe.id))


@router.get("/portfolios/{recommendation_id}")
async def portfolio(
    recommendation_id: int,
    market: QuantMarket = "US",
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    result = repo.portfolio(recommendation_id, market, universe.id)
    if not result:
        raise HTTPException(404, "Portfolio recommendation not found")
    row, items = result
    return {**encoded(row), "items": encoded(items)}


@router.get("/intraday-confirmations")
async def confirmations(
    market: QuantMarket = "US",
    trade_date: date | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return encoded(repo.confirmations(market, trade_date, universe_id=universe.id))


@router.get("/intraday-confirmations/{code}")
async def confirmation(
    code: str,
    market: QuantMarket = "US",
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return encoded(repo.confirmations(market, code=code, universe_id=universe.id))


@router.post("/intraday-confirmations/run")
async def run_confirmation(
    body: IntradayRunRequest,
    market: QuantMarket = "US",
    _: User = Depends(require_admin),
):
    if market != "US":
        raise HTTPException(409, "CN intraday confirmation is not available")
    from finance_analysis.quant.intraday_confirmation.runner import IntradayConfirmationRunner

    return IntradayConfirmationRunner().run(body.trade_date or date.today(), market=market)

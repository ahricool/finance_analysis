"""Authenticated, explicitly market-scoped quant research API."""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.quant import (
    DatasetBuildRequest,
    ModelRunCreateRequest,
    PublishRequest,
)
from finance_analysis.quant.capabilities import get_quant_capabilities
from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.markets import get_universe_codes
from finance_analysis.quant.models import QLIB_TRAINABLE_MODEL_KEYS
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS

router = APIRouter()
QuantMarket = Literal["US", "CN"]
logger = logging.getLogger(__name__)


def encoded(value):
    return jsonable_encoder(value)


def _encoded_with_names(
    repo: QuantRepository,
    rows,
    *,
    code_field: str = "code",
    name_field: str = "name",
) -> list[dict]:
    """Attach persisted security names to a batch without provider or N+1 calls."""
    payloads = encoded(rows)
    codes = [str(item.get(code_field) or "").upper() for item in payloads]
    names_by_codes = getattr(repo, "names_by_codes", None)
    names = names_by_codes(codes) if callable(names_by_codes) else {}
    for item, code in zip(payloads, codes):
        item[name_field] = names.get(code) or item.get(name_field)
    return payloads


def _encoded_with_name(
    repo: QuantRepository,
    row,
    *,
    code_field: str = "code",
    name_field: str = "name",
) -> dict:
    return _encoded_with_names(repo, [row], code_field=code_field, name_field=name_field)[0]


def _universe(repo: QuantRepository, market: str, key: str | None):
    try:
        return repo.supported_universe(market, key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def _dataset_payload(row) -> dict:
    universe_members = len(get_universe_codes(row.market))
    dataset_symbols = int(row.symbol_count or 0)
    coverage_ratio = dataset_symbols / universe_members if universe_members else 0.0
    minimum_coverage = get_quant_config().minimum_universe_coverage
    return {
        **encoded(row),
        "universe_member_count": universe_members,
        "universe_coverage_ratio": coverage_ratio,
        "minimum_universe_coverage": minimum_coverage,
        "trainable": (row.status == "ready" and bool(row.artifact_uri) and coverage_ratio >= minimum_coverage),
    }


def _market_regime_payload(row) -> dict:
    """Expose the persisted v2 score explanation while preserving legacy snapshots."""
    payload = encoded(row)
    features = payload.get("features") if isinstance(payload, dict) else None
    payload["score_breakdown"] = features.get("score_breakdown") if isinstance(features, dict) else None
    return payload


def _remove_artifact(artifact_uri: str | None) -> bool:
    if not artifact_uri:
        return False
    try:
        return ArtifactStore().delete_uri(artifact_uri)
    except (OSError, ValueError) as exc:
        logger.exception("Quant database record was deleted but artifact cleanup failed: uri=%s", artifact_uri)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Database record was deleted, but artifact cleanup failed",
        ) from exc


@router.get("/capabilities")
async def capabilities(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    return get_quant_capabilities(market)


@router.get("/universes")
async def universes(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    item = _universe(repo, market, None)
    codes = sorted(get_universe_codes(market))
    names_by_codes = getattr(repo, "names_by_codes", None)
    names = names_by_codes(codes) if callable(names_by_codes) else {}
    return [
        {
            **encoded(item),
            "member_count": len(codes),
            "members": [
                {
                    "code": code,
                    "name": names.get(code),
                    "sector_key": None,
                    "sector_benchmark_code": None,
                    "effective_from": None,
                    "effective_to": None,
                }
                for code in codes
            ],
        }
    ]


@router.get("/models/definitions")
async def model_definitions(market: QuantMarket = "US", _: User = Depends(require_current_user)):
    return encoded(
        [
            row
            for row in QuantRepository().list_model_definitions()
            if row.enabled and row.key in QLIB_TRAINABLE_MODEL_KEYS and market in (row.supported_markets or [])
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
    return [_dataset_payload(row) for row in repo.list_datasets(market=market, universe_id=universe.id)]


@router.get("/datasets/{snapshot_id}")
async def dataset(snapshot_id: int, market: QuantMarket = "US", _: User = Depends(require_current_user)):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    row = repo.get_dataset(snapshot_id)
    if not row or row.market != market or row.universe_id != universe.id:
        raise HTTPException(404, "Dataset snapshot not found")
    return _dataset_payload(row)


@router.delete("/datasets/{snapshot_id}")
async def delete_dataset(
    snapshot_id: int,
    market: QuantMarket = "US",
    _: User = Depends(require_admin),
):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    try:
        deleted = repo.delete_dataset(snapshot_id, market, universe.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset snapshot not found")
    artifact_deleted = _remove_artifact(deleted["artifact_uri"])
    return {"id": deleted["id"], "deleted": True, "artifact_deleted": artifact_deleted}


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
    return _market_regime_payload(rows[0])


@router.get("/market-regime/history")
async def market_regime_history(
    market: QuantMarket = "US",
    date_from: date | None = None,
    date_to: date | None = None,
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    return [
        _market_regime_payload(row)
        for row in QuantRepository().market_regimes(
            market,
            date_from,
            date_to,
            model_version=model_version,
        )
    ]


@router.get("/sectors/ranking")
async def sector_ranking(
    market: QuantMarket = "US",
    trade_date: date | None = None,
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    return _encoded_with_names(
        repo,
        repo.sector_regimes(
            market,
            trade_date,
            model_version=model_version,
        ),
        code_field="benchmark_code",
        name_field="benchmark_name",
    )


@router.get("/sectors/{sector_key}")
async def sector_detail(
    sector_key: str,
    market: QuantMarket = "US",
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    return _encoded_with_names(
        repo,
        repo.sector_regimes(
            market,
            sector_key=sector_key,
            model_version=model_version,
        ),
        code_field="benchmark_code",
        name_field="benchmark_name",
    )


@router.post("/model-runs", status_code=status.HTTP_202_ACCEPTED)
async def create_model_run(body: ModelRunCreateRequest, user: User = Depends(require_admin)):
    repo = QuantRepository()
    market = body.market.upper()
    universe = _universe(repo, market, body.universe)
    definition = repo.get_model_definition(body.model_key)
    dataset = repo.get_dataset(body.dataset_snapshot_id)
    if not definition or not definition.enabled or definition.key not in QLIB_TRAINABLE_MODEL_KEYS or not dataset:
        raise HTTPException(400, "Unknown model or dataset")
    if market not in (definition.supported_markets or []):
        raise HTTPException(400, f"Model {body.model_key} does not support {market}")
    if dataset.market != market or dataset.universe_id != universe.id:
        raise HTTPException(409, "Model run, universe, and dataset market must match")
    if dataset.status != "ready":
        raise HTTPException(409, "Dataset is not ready")
    universe_members = len(get_universe_codes(market))
    coverage_ratio = int(dataset.symbol_count or 0) / universe_members if universe_members else 0.0
    minimum_coverage = get_quant_config().minimum_universe_coverage
    if coverage_ratio < minimum_coverage:
        raise HTTPException(
            409,
            f"Dataset universe coverage {coverage_ratio:.2%} is below the " f"{minimum_coverage:.2%} minimum",
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
    return {"model_run_id": run.id, "task_id": task.id, "status": "pending", "market": market}


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


@router.delete("/model-runs/{run_id}")
async def delete_model_run(
    run_id: int,
    market: QuantMarket = "US",
    _: User = Depends(require_admin),
):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    try:
        deleted = repo.delete_model_run(run_id, market, universe.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model run not found")
    artifact_deleted = _remove_artifact(deleted["artifact_uri"])
    return {"id": deleted["id"], "deleted": True, "artifact_deleted": artifact_deleted}


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
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    definition = _universe(repo, market, universe)
    rows = repo.latest_signals(market, definition.id, model_version=model_version)
    regimes = (
        repo.market_regimes(market, date_from=rows[0].trade_date, date_to=rows[0].trade_date, limit=1) if rows else []
    )
    return {
        "trade_date": rows[0].trade_date if rows else None,
        "market": market,
        "universe": definition.key,
        "model_version": rows[0].model_version if rows else model_version,
        "market_regime": regimes[0].regime if regimes else None,
        "max_equity_exposure": regimes[0].max_equity_exposure if regimes else None,
        "items": _encoded_with_names(repo, rows),
    }


@router.get("/signals/{code}")
async def signal(
    code: str,
    market: QuantMarket = "US",
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    rows = repo.latest_signals(
        market,
        universe.id,
        code=code,
        model_version=model_version,
    )
    if not rows:
        raise HTTPException(404, f"{market} signal not found")
    return _encoded_with_name(repo, rows[0])


@router.get("/signals/{code}/history")
async def signal_history(
    code: str,
    market: QuantMarket = "US",
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return _encoded_with_names(
        repo,
        repo.signal_history(
            market,
            code,
            universe.id,
            model_version=model_version,
        ),
    )


@router.get("/portfolios/latest")
async def latest_portfolio(
    market: QuantMarket = "US",
    universe: str | None = None,
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    definition = _universe(repo, market, universe)
    rows = repo.latest_portfolios(
        market,
        definition.id,
        1,
        model_version=model_version,
    )
    if not rows:
        raise HTTPException(404, f"{market} portfolio recommendation not found")
    result = repo.portfolio(rows[0].id, market, definition.id)
    if not result:
        raise HTTPException(404, "Portfolio recommendation not found")
    row, items = result
    return {**encoded(row), "universe": definition.key, "items": _encoded_with_names(repo, items)}


@router.get("/portfolios")
async def portfolios(
    market: QuantMarket = "US",
    model_version: str | None = None,
    _: User = Depends(require_current_user),
):
    repo = QuantRepository()
    universe = _universe(repo, market, None)
    return encoded(
        repo.latest_portfolios(
            market,
            universe.id,
            model_version=model_version,
        )
    )


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
    return {**encoded(row), "universe": universe.key, "items": _encoded_with_names(repo, items)}

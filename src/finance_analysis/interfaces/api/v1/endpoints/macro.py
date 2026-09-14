"""Authenticated read-only shared macro data; no synchronization endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.macro import DashboardResponse, SeriesResponse
from finance_analysis.macro.models import SeriesMode, SeriesRange
from finance_analysis.macro.service import MacroService

router = APIRouter(dependencies=[Depends(require_current_user)])


def get_macro_service() -> MacroService:
    return MacroService()


def _csv(value: str | None) -> list[str] | None:
    return None if value is None else [part.strip().upper() for part in value.split(",") if part.strip()]


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(as_of: date | None = None, service: MacroService = Depends(get_macro_service)):
    return service.dashboard(as_of)


@router.get("/series", response_model=SeriesResponse)
def series(
    range: SeriesRange = "60d",
    mode: SeriesMode = "normalized",
    symbols: str | None = Query(None, max_length=512),
    series: str | None = Query(None, max_length=256),
    benchmark: str = "SPY.US",
    as_of: date | None = None,
    service: MacroService = Depends(get_macro_service),
):
    try:
        return service.series(
            range=range,
            mode=mode,
            symbols=_csv(symbols),
            series=_csv(series),
            benchmark=benchmark.strip().upper(),
            as_of=as_of,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

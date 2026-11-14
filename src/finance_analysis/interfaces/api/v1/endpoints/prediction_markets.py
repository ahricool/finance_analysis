"""Logged-in stock search; no business writes, tasks, or LLM calls."""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Path

from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.integrations.market_data.normalizer import canonical_symbol
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.prediction_markets import SearchResponse, LiveResponse, HistoryResponse
from finance_analysis.prediction_markets.live import get_live_service
from finance_analysis.prediction_markets.search import search_stock

router = APIRouter(dependencies=[Depends(require_current_user)])


def instruments():
    return InstrumentRepository()


@router.get("/stocks/{symbol}", response_model=SearchResponse)
def search(symbol: str, repo=Depends(instruments)):
    try:
        symbol = canonical_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    instrument = repo.get_by_code(symbol)
    # Code search remains available when the public master record/name is missing.
    return search_stock(symbol, instrument.name if instrument else None)


@router.get("/events/{event_id}/live", response_model=LiveResponse)
def live(event_id: str = Path(pattern=r"^[0-9]{1,80}$")):
    return get_live_service().live(event_id)


@router.get("/events/{event_id}/history", response_model=HistoryResponse)
def history(
    market_id: str,
    outcome_id: str,
    event_id: str = Path(pattern=r"^[0-9]{1,80}$"),
    window: Literal["1d", "1w", "1m", "max"] = "1w",
):
    try:
        return get_live_service().history(event_id, market_id, outcome_id, window)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

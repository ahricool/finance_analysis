"""Shared market heatmap; no external requests or task dispatch from GET."""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends

from finance_analysis.core.time import utc_now
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.market_heatmap import HeatmapResponse
from finance_analysis.market_heatmap.cache import HeatmapCache
from finance_analysis.market_heatmap.config import REFRESH_SECONDS

router = APIRouter(dependencies=[Depends(require_current_user)])


@router.get("", response_model=HeatmapResponse)
def get_heatmap(market: Literal["CN", "US"] = "CN"):
    payload = HeatmapCache().read(market)
    if payload is None:
        return {"status": "empty", "snapshot": None}
    generated = datetime.fromisoformat(payload["generated_at"])
    stale = utc_now() - generated > timedelta(seconds=REFRESH_SECONDS * 2)
    return {"status": "stale" if stale else "ready", "snapshot": payload}

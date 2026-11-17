"""Authenticated fixed-universe screen; GET never requests remote market data."""

import asyncio

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Response

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.intraday_options import IntradayOptionsResponse
from finance_analysis.intraday_options.config import SYMBOLS
from finance_analysis.intraday_options.runtime import read_snapshot
from finance_analysis.market_stream.config import MarketStreamConfig

router = APIRouter(dependencies=[Depends(require_current_user)])


def load_names():
    return InstrumentRepository().names_by_codes(SYMBOLS)


@router.get("", response_model=IntradayOptionsResponse)
async def snapshot(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    repository = RealtimeStateRepository.from_url(MarketStreamConfig.from_env().redis_url)
    try:
        names = await asyncio.to_thread(load_names)
        return await full_snapshot(repository, names, utc_now())
    except Exception as exc:
        raise HTTPException(503, "日内期权行情暂时不可用，请稍后重试") from exc
    finally:
        with CancelScope(shield=True):
            await repository.close()


async def full_snapshot(repository, names, now, after_event_id=None):
    from finance_analysis.database.repositories.intraday_simulation import read

    result = await read_snapshot(repository, names, now)
    result["simulation"] = await asyncio.to_thread(read, result["trading_date"], after_event_id)
    from finance_analysis.database.repositories.intraday_simulation import references

    try:
        result["simulation"]["references"] = await asyncio.to_thread(references, result["trading_date"])
    except Exception:
        result["simulation"]["references"] = {
            "background": {"label": "未知", "as_of": None, "reason": "参考数据暂不可用"},
            "macro": [],
            "macro_status": "宏观日历暂不可用，风险未知",
        }
    return result

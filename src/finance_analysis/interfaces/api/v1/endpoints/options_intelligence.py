"""Read-only views; explicit refresh/explain actions publish tracked Celery tasks."""

from fastapi import APIRouter, Depends, HTTPException, Query
from finance_analysis.interfaces.api.deps import require_current_user, require_admin
from finance_analysis.interfaces.api.v1.schemas.options_intelligence import (
    OptionsRunRequest,
    OptionsTaskAccepted,
    OptionsScanResponse,
    OptionsDetailResponse,
)
from finance_analysis.options_intelligence.config import get_options_config
from finance_analysis.options_intelligence.service import us_symbol
from finance_analysis.database.repositories.options_intelligence import OptionsRepository

from finance_analysis.options_intelligence.views import current_view, scan_view

router = APIRouter()


def validated_symbol(symbol):
    try:
        return us_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def submit(user, symbol=None, explain=False):
    from finance_analysis.tasks.celery.jobs.options_intelligence.tasks import options_request

    if not get_options_config().enabled:
        raise HTTPException(409, "期权分析已关闭")
    try:
        task = options_request.apply_async(
            kwargs={
                "symbol": symbol,
                "explain": explain,
                "owner_uid": user.id,
                "_trigger_source": "manual",
                "_triggered_by_uid": user.id,
            },
            queue="ingestion",
            expires=1800,
        )
    except Exception as exc:
        raise HTTPException(503, "无法提交期权分析任务") from exc
    return {"task_id": task.id, "status": "pending"}


@router.get("", response_model=OptionsScanResponse)
def scan(user=Depends(require_current_user)):
    repo = OptionsRepository()
    symbols = repo.monitored_symbols(get_options_config().default_symbols, uid=user.id)
    return {"items": [scan_view(row) for row in repo.scan(symbols)]}


@router.post("/run", status_code=202, response_model=OptionsTaskAccepted)
def run(body: OptionsRunRequest, user=Depends(require_admin)):
    return submit(user, validated_symbol(body.symbol) if body.symbol else None)


@router.get("/{symbol}", response_model=OptionsDetailResponse)
def detail(symbol: str, history_limit: int = Query(90, ge=1, le=120), user=Depends(require_current_user)):
    from finance_analysis.integrations.market_data.service import MarketDataService
    from finance_analysis.options_intelligence.evaluation import with_evaluations

    symbol = validated_symbol(symbol)
    repo = OptionsRepository()
    latest = current_view(repo.latest(symbol))
    events = with_evaluations(repo.events(symbol), MarketDataService())
    return {
        "symbol": symbol,
        "latest": latest,
        "daily_history": repo.daily(symbol, history_limit),
        "events": events,
        "analyses": repo.analysis_history(symbol),
        "reason": None if latest else "尚未采集该美股期权链，可点击刷新异步采集",
    }


@router.post("/{symbol}/refresh", status_code=202, response_model=OptionsTaskAccepted)
def refresh(symbol: str, user=Depends(require_current_user)):
    return submit(user, validated_symbol(symbol))


@router.post("/{symbol}/explain", status_code=202, response_model=OptionsTaskAccepted)
def explain(symbol: str, user=Depends(require_current_user)):
    symbol = validated_symbol(symbol)
    if OptionsRepository().latest(symbol) is None:
        raise HTTPException(409, "请先采集期权链")
    return submit(user, symbol, True)

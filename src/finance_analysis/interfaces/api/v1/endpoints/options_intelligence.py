"""Read-only views; explicit refresh/explain actions publish tracked Celery tasks."""

from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import date
from typing import Literal
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

from finance_analysis.options_intelligence.views import scan_view
from finance_analysis.options_intelligence.preview_cache import load_preview

router = APIRouter()


def validated_symbol(symbol):
    try:
        return us_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def submit(user, symbol=None, explain=False, view=None, trade_date=None):
    from finance_analysis.tasks.celery.jobs.options_intelligence.tasks import options_request

    if not get_options_config().enabled:
        raise HTTPException(409, "期权分析已关闭")
    try:
        task = options_request.apply_async(
            kwargs={
                "symbol": symbol,
                "explain": explain,
                "view": view,
                "trade_date": trade_date.isoformat() if trade_date else None,
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
def scan(
    view: Literal["preview", "official"] = "official",
    trade_date: date | None = None,
    user=Depends(require_current_user),
):
    repo = OptionsRepository()
    symbols = repo.monitored_symbols(uid=user.id)
    dates = repo.dates(symbols)
    if view == "preview":
        payload = load_preview()
        successes = {row["symbol"]: row for row in (payload or {}).get("items", [])}
        failures = {row["symbol"]: row for row in (payload or {}).get("failures", [])}
        items = (
            [
                (
                    scan_view(successes[symbol])
                    if symbol in successes
                    else {
                        "symbol": symbol,
                        "status": "failed" if symbol in failures else "not_scanned",
                        "scores": None,
                        "limitations": [failures[symbol]["reason"]] if symbol in failures else ["本轮预演尚未采集"],
                    }
                )
                for symbol in symbols
            ]
            if payload
            else []
        )
        return {
            "items": items,
            "view": view,
            "trade_date": (payload or {}).get("trade_date"),
            "available_dates": dates,
            "observed_at": (payload or {}).get("observed_at"),
            "reason": None if payload else "暂无今日盘中预演，等待交易时段扫描",
            "failed_count": sum(symbol in failures for symbol in symbols),
        }
    selected = trade_date or (dates[0] if dates else None)
    return {
        "items": [scan_view(row) for row in repo.scan(symbols, selected)],
        "view": view,
        "trade_date": selected,
        "available_dates": dates,
    }


@router.post("/run", status_code=202, response_model=OptionsTaskAccepted)
def run(body: OptionsRunRequest, user=Depends(require_admin)):
    return submit(user, validated_symbol(body.symbol) if body.symbol else None, view=body.view)


@router.get("/{symbol}", response_model=OptionsDetailResponse)
def detail(
    symbol: str,
    history_limit: int = Query(90, ge=1, le=120),
    view: Literal["preview", "official"] = "official",
    trade_date: date | None = None,
    user=Depends(require_current_user),
):
    from finance_analysis.integrations.market_data.service import MarketDataService
    from finance_analysis.options_intelligence.evaluation import with_evaluations

    symbol = validated_symbol(symbol)
    repo = OptionsRepository()
    dates = repo.dates([symbol])
    selected = trade_date or (dates[0] if dates else None)
    if view == "preview":
        latest = load_preview(symbol=symbol)
        selected = date.fromisoformat(latest["trade_date"]) if latest else None
    else:
        latest = repo.latest(symbol, selected)
    events = with_evaluations(repo.events(symbol, through=selected), MarketDataService())
    return {
        "symbol": symbol,
        "latest": latest,
        "daily_history": repo.daily(symbol, history_limit, through=selected),
        "events": events,
        "analyses": repo.analysis_history(symbol, through=selected),
        "view": view,
        "trade_date": selected,
        "available_dates": dates,
        "reason": None if latest else ("暂无今日盘中预演" if view == "preview" else "所选日期尚无正式期权数据"),
    }


@router.post("/{symbol}/refresh", status_code=202, response_model=OptionsTaskAccepted)
def refresh(symbol: str, body: OptionsRunRequest | None = None, user=Depends(require_current_user)):
    return submit(user, validated_symbol(symbol), view=body.view if body else None)


@router.post("/{symbol}/explain", status_code=202, response_model=OptionsTaskAccepted)
def explain(symbol: str, trade_date: date | None = None, user=Depends(require_current_user)):
    symbol = validated_symbol(symbol)
    if OptionsRepository().latest(symbol, trade_date) is None:
        raise HTTPException(409, "请先采集期权链")
    return submit(user, symbol, True, trade_date=trade_date)

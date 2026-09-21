"""CN/US Trade Engine every 30 minutes on the alerts queue. No dedicated worker."""

from __future__ import annotations

import time
from typing import Any, Optional

from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open  # pragma: allowlist secret
from finance_analysis.tasks.celery.app import celery_app  # pragma: allowlist secret
from finance_analysis.tasks.celery.schedule import (  # pragma: allowlist secret
    JOB_TRADE_ENGINE_CN,
    JOB_TRADE_ENGINE_US,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import TaskSkipped, track_task  # pragma: allowlist secret
from finance_analysis.trade_engine.bars import in_evaluation_window  # pragma: allowlist secret
from finance_analysis.trade_engine.service import TradeEngineService  # pragma: allowlist secret

CN_DEFINITION = require_scheduled_task_definition(JOB_TRADE_ENGINE_CN)
US_DEFINITION = require_scheduled_task_definition(JOB_TRADE_ENGINE_US)


def _run_market(market: str) -> dict[str, Any]:
    started = time.perf_counter()
    now = get_market_now(market.lower())
    if not is_market_open(market.lower(), now.date()):
        raise TaskSkipped(f"{market} 当天不是交易日，跳过交易引擎")
    if not in_evaluation_window(market, now):
        raise TaskSkipped(f"{market} 当前不在常规交易时段，跳过交易引擎")
    result = TradeEngineService().evaluate_market(market, now=now)
    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return {
        "market": market,
        "positions_analyzed": int(result.get("positions_analyzed") or 0),
        "candidates": int(result.get("candidates") or 0),
        "proposals": int(result.get("proposals") or result.get("candidates") or 0),
        "llm_reviews": int(result.get("llm_reviews") or 0),
        "confirmed_signals": int(result.get("confirmed_signals") or 0),
        "rejected_signals": int(result.get("rejected_signals") or 0),
        "resolved_no_action": int(result.get("resolved_no_action") or 0),
        "notifications": int(result.get("notifications") or 0),
        "elapsed_ms": result["elapsed_ms"],
        "status": result.get("status") or "OK",
    }


@celery_app.task(
    name=CN_DEFINITION.celery_task_name,
    time_limit=600,
    soft_time_limit=540,
    expires=CN_DEFINITION.expires,
)
@track_task(
    task_type=CN_DEFINITION.task_type,
    task_name=CN_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN_DEFINITION.job_id,
    record_result=True,
    success_message="A股交易引擎完成",
    strip_lifecycle_kwargs=True,
)
def run_trade_engine_cn(scheduler_job_id: Optional[str] = None, **_: Any) -> dict[str, Any]:
    del scheduler_job_id
    return _run_market("CN")


@celery_app.task(
    name=US_DEFINITION.celery_task_name,
    time_limit=600,
    soft_time_limit=540,
    expires=US_DEFINITION.expires,
)
@track_task(
    task_type=US_DEFINITION.task_type,
    task_name=US_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=US_DEFINITION.job_id,
    record_result=True,
    success_message="美股交易引擎完成",
    strip_lifecycle_kwargs=True,
)
def run_trade_engine_us(scheduler_job_id: Optional[str] = None, **_: Any) -> dict[str, Any]:
    del scheduler_job_id
    return _run_market("US")


__all__ = ["run_trade_engine_cn", "run_trade_engine_us"]

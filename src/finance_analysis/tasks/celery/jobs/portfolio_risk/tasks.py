"""Minute CN/US portfolio-risk evaluation on the alerts queue. No dedicated risk-worker."""

from __future__ import annotations

import time
from typing import Any, Optional

from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open  # pragma: allowlist secret
from finance_analysis.portfolio_risk.bars import in_evaluation_window  # pragma: allowlist secret
from finance_analysis.portfolio_risk.service import PortfolioRiskService  # pragma: allowlist secret
from finance_analysis.tasks.celery.app import celery_app  # pragma: allowlist secret
from finance_analysis.tasks.celery.schedule import (  # pragma: allowlist secret
    JOB_PORTFOLIO_RISK_CN,
    JOB_PORTFOLIO_RISK_US,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import TaskSkipped, track_task  # pragma: allowlist secret

CN_DEFINITION = require_scheduled_task_definition(JOB_PORTFOLIO_RISK_CN)
US_DEFINITION = require_scheduled_task_definition(JOB_PORTFOLIO_RISK_US)


def _run_market(market: str) -> dict[str, Any]:
    started = time.perf_counter()
    now = get_market_now(market.lower())
    if not is_market_open(market.lower(), now.date()):
        raise TaskSkipped(f"{market} 当天不是交易日，跳过持仓风控")
    if not in_evaluation_window(market, now):
        raise TaskSkipped(f"{market} 当前不在常规交易时段，跳过持仓风控")
    service = PortfolioRiskService()
    sources = service.sources.list_enabled()
    evaluated = 0
    notified = 0
    skipped = 0
    for source in sources:
        result = service.evaluate_uid(source.uid, market_filter=market, now=now)
        status = result.get("status")
        if status == "OK":
            evaluated += 1
            notified += int(result.get("notified") or 0)
        else:
            skipped += 1
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "status": "completed",
        "market": market,
        "sources": len(sources),
        "evaluated": evaluated,
        "skipped": skipped,
        "notified": notified,
        "elapsed_ms": elapsed_ms,
    }


@celery_app.task(
    name=CN_DEFINITION.celery_task_name,
    time_limit=50,
    soft_time_limit=40,
    expires=CN_DEFINITION.expires,
)
@track_task(
    task_type=CN_DEFINITION.task_type,
    task_name=CN_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN_DEFINITION.job_id,
    record_result=True,
    success_message="A股持仓分钟风控完成",
    strip_lifecycle_kwargs=True,
)
def run_portfolio_risk_cn(scheduler_job_id: Optional[str] = None, **_: Any) -> dict[str, Any]:
    del scheduler_job_id
    return _run_market("CN")


@celery_app.task(
    name=US_DEFINITION.celery_task_name,
    time_limit=50,
    soft_time_limit=40,
    expires=US_DEFINITION.expires,
)
@track_task(
    task_type=US_DEFINITION.task_type,
    task_name=US_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=US_DEFINITION.job_id,
    record_result=True,
    success_message="美股持仓分钟风控完成",
    strip_lifecycle_kwargs=True,
)
def run_portfolio_risk_us(scheduler_job_id: Optional[str] = None, **_: Any) -> dict[str, Any]:
    del scheduler_job_id
    return _run_market("US")


__all__ = ["run_portfolio_risk_cn", "run_portfolio_risk_us"]

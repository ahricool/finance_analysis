"""Celery entry points for the CN and US market-close daily sync schedules."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date
from typing import Any, Optional

from kombu.exceptions import OperationalError

from finance_analysis.market_review.trading_calendar import get_completed_trading_days
from finance_analysis.minute_forecast.publisher import forecast_model, forecast_url
from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock, TaskAdvisoryLockId
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.metadata import DAILY_KRONOS_TASK
from finance_analysis.tasks.celery.schedule import (
    JOB_MARKET_DATA_SYNC_CN,
    JOB_MARKET_DATA_SYNC_US,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import TaskExecutionStatus, TaskOutcome, TaskSkipped, track_task
from finance_analysis.tasks.outcomes import market_sync_outcome

from .models import normalize_sync_mode
from .service import MarketDataSyncError, MarketDataSyncService, resolve_daily_sync_scope

CN_DEFINITION = require_scheduled_task_definition(JOB_MARKET_DATA_SYNC_CN)
US_DEFINITION = require_scheduled_task_definition(JOB_MARKET_DATA_SYNC_US)
DAILY_KRONOS_LOCKS = {"CN": TaskAdvisoryLockId.DAILY_KRONOS_CN, "US": TaskAdvisoryLockId.DAILY_KRONOS_US}
logger = logging.getLogger(__name__)


def _sync_and_dispatch(market: str, sync_mode: str) -> dict[str, Any]:
    summary = MarketDataSyncService(market=market, sync_mode=sync_mode).run()
    if forecast_url():
        try:
            forecast = forecast_daily_market.delay(market, summary["trade_date"])
            summary["kronos_forecast_task_id"] = forecast.id
        except OperationalError:
            logger.exception("Could not enqueue daily Kronos forecast: market=%s", market)
            summary["kronos_forecast_dispatch_failed"] = True
            summary["sync_status"] = "partial"
    return summary


def _daily_forecast_outcome(result: dict[str, Any]) -> TaskOutcome | None:
    if result["predicted_symbols"] < result["scope_symbols"]:
        return TaskOutcome(
            TaskExecutionStatus.PARTIAL,
            f"日 K 预测覆盖 {result['predicted_symbols']}/{result['scope_symbols']} 个标的",
        )
    return None


@celery_app.task(name=DAILY_KRONOS_TASK.celery_name)
@track_task(
    task_type=DAILY_KRONOS_TASK.task_type, task_name=DAILY_KRONOS_TASK.display_name,
    source=DAILY_KRONOS_TASK.source, outcome_getter=_daily_forecast_outcome,
)
def forecast_daily_market(market: str, trade_date: str) -> dict[str, Any]:
    from finance_analysis.daily_forecast.service import run_daily_forecast
    from finance_analysis.database.repositories.daily_forecast import DailyForecastRepository
    from finance_analysis.database.repositories.universe import UniverseResolver

    url = forecast_url()
    if not url:
        raise TaskSkipped("Kronos 服务未配置")
    as_of = date.fromisoformat(trade_date)
    with PostgreSQLAdvisoryLock(DAILY_KRONOS_LOCKS[market], blocking=True):
        if as_of != get_completed_trading_days(market.lower(), 1)[0]:
            raise TaskSkipped("日线同步日期已不是最新收盘交易日")
        scope = resolve_daily_sync_scope(market, UniverseResolver())
        if not scope:
            raise MarketDataSyncError(f"No enabled daily symbols in the {market} synchronization scope")
        result = run_daily_forecast(
            market, as_of, [instrument.id for instrument in scope], url, forecast_model(), DailyForecastRepository(),
        )
        if not result["published"]:
            raise TaskSkipped("市场已有更新的 Kronos 日 K 预测")
        return result


def _run_markets(markets: tuple[str, ...], sync_mode: str = "incremental") -> dict[str, Any]:
    sync_mode = normalize_sync_mode(sync_mode)
    summaries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for market in markets:
        try:
            summaries.append(_sync_and_dispatch(market, sync_mode))
        except Exception as exc:
            errors.append({"market": market, "reason": str(exc)})
    if not summaries:
        detail = "; ".join(f"{item['market']}: {item['reason']}" for item in errors)
        raise MarketDataSyncError(f"All requested markets failed: {detail}")
    providers = Counter()
    for summary in summaries:
        providers.update(summary["provider_counts"])
    fallbacks = [item for summary in summaries for item in summary["fallback_reasons"]]
    fallbacks.extend(errors)
    return {
        "sync_status": "partial" if errors or any(s["sync_status"] == "partial" for s in summaries) else "success",
        "sync_mode": sync_mode,
        "market": ",".join(markets),
        "symbol_count": sum(summary["symbol_count"] for summary in summaries),
        "success_symbols": sum(summary["success_symbols"] for summary in summaries),
        "partial_symbols": sum(summary["partial_symbols"] for summary in summaries),
        "failed_symbols": sum(summary["failed_symbols"] for summary in summaries),
        "inserted_rows": sum(summary["inserted_rows"] for summary in summaries),
        "updated_rows": sum(summary["updated_rows"] for summary in summaries),
        "provider_counts": dict(providers),
        "missing_amount_symbols": sorted(code for summary in summaries for code in summary["missing_amount_symbols"]),
        "fallback_reasons": fallbacks[:20],
        "per_market": {summary["market"]: summary for summary in summaries},
        "market_errors": errors,
        "kronos_forecast_dispatch_failed": any(s.get("kronos_forecast_dispatch_failed") for s in summaries),
    }


@celery_app.task(name=CN_DEFINITION.celery_task_name)
@track_task(
    task_type=CN_DEFINITION.task_type,
    task_name=CN_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN_DEFINITION.job_id,
    record_result=True,
    outcome_getter=market_sync_outcome,
    strip_lifecycle_kwargs=True,
    advisory_lock_id=TaskAdvisoryLockId.CN_DAILY_MARKET_DATA_SYNC,
)
def sync_cn_market_data(
    scheduler_job_id: Optional[str] = None,
    sync_mode: str = "incremental",
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    return _run_markets(("CN",), sync_mode=sync_mode)


@celery_app.task(name=US_DEFINITION.celery_task_name)
@track_task(
    task_type=US_DEFINITION.task_type,
    task_name=US_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=US_DEFINITION.job_id,
    record_result=True,
    outcome_getter=market_sync_outcome,
    strip_lifecycle_kwargs=True,
    advisory_lock_id=TaskAdvisoryLockId.US_DAILY_MARKET_DATA_SYNC,
)
def sync_us_market_data(
    scheduler_job_id: Optional[str] = None,
    sync_mode: str = "incremental",
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    return _sync_and_dispatch("US", sync_mode)


__all__ = ["forecast_daily_market", "sync_cn_market_data", "sync_us_market_data"]

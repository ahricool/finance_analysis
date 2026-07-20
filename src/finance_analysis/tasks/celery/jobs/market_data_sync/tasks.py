"""Celery entry points for the CN and US market-close daily sync schedules."""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import (
    JOB_MARKET_DATA_SYNC_CN_HK,
    JOB_MARKET_DATA_SYNC_US,
    require_scheduled_task_definition,
)
from finance_analysis.tasks.lifecycle import track_task

from .models import normalize_sync_mode
from .service import MarketDataSyncError, MarketDataSyncService

CN_HK_DEFINITION = require_scheduled_task_definition(JOB_MARKET_DATA_SYNC_CN_HK)
US_DEFINITION = require_scheduled_task_definition(JOB_MARKET_DATA_SYNC_US)


def _run_markets(markets: tuple[str, ...], sync_mode: str = "incremental") -> dict[str, Any]:
    sync_mode = normalize_sync_mode(sync_mode)
    summaries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for market in markets:
        try:
            summaries.append(MarketDataSyncService(market=market, sync_mode=sync_mode).run())
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
    unsupported = [item for summary in summaries for item in summary["unsupported_symbols"]]
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
        "provider_vwap_symbols": sorted(code for summary in summaries for code in summary["provider_vwap_symbols"]),
        "calculated_vwap_symbols": sorted(code for summary in summaries for code in summary["calculated_vwap_symbols"]),
        "estimated_vwap_symbols": sorted(code for summary in summaries for code in summary["estimated_vwap_symbols"]),
        "missing_vwap_symbols": sorted(code for summary in summaries for code in summary["missing_vwap_symbols"]),
        "unsupported_symbol_count": len(unsupported),
        "unsupported_symbols": unsupported,
        "fallback_reasons": fallbacks[:20],
        "per_market": {summary["market"]: summary for summary in summaries},
        "market_errors": errors,
    }


@celery_app.task(name=CN_HK_DEFINITION.celery_task_name)
@track_task(
    task_type=CN_HK_DEFINITION.task_type,
    task_name=CN_HK_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN_HK_DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
    dedupe_key=f"scheduled:{CN_HK_DEFINITION.job_id}",
)
def sync_cn_hk_market_data(
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
    strip_lifecycle_kwargs=True,
    dedupe_key=f"scheduled:{US_DEFINITION.job_id}",
)
def sync_us_market_data(
    scheduler_job_id: Optional[str] = None,
    sync_mode: str = "incremental",
    **_: Any,
) -> dict[str, Any]:
    del scheduler_job_id
    return MarketDataSyncService(market="US", sync_mode=sync_mode).run()


__all__ = ["sync_cn_hk_market_data", "sync_us_market_data"]

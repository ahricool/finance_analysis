"""Scheduled and manual/backfill entry points using existing task lifecycle."""

from datetime import date
from finance_analysis.market_structure.service import MarketStructureService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task, TaskSkipped
from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open


def _run(market, trade_date=None, start_date=None, end_date=None):
    service = MarketStructureService(market)
    if start_date is not None or end_date is not None:
        if not start_date or not end_date:
            raise ValueError("Both start_date and end_date are required")
        return service.backfill(date.fromisoformat(start_date), date.fromisoformat(end_date))
    if not trade_date and not is_market_open(market.lower(), get_market_now(market.lower()).date()):
        raise TaskSkipped("非交易日，跳过市场结构")
    return service.run(date.fromisoformat(trade_date) if trade_date else None)


CN_DEFINITION = require_scheduled_task_definition("market_structure_cn")


@celery_app.task(name=CN_DEFINITION.celery_task_name)
@track_task(
    task_type=CN_DEFINITION.task_type,
    task_name=CN_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN_DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def run_market_structure_cn(trade_date=None, start_date=None, end_date=None, **kwargs):
    return _run("CN", trade_date, start_date, end_date)


US_DEFINITION = require_scheduled_task_definition("market_structure_us")


@celery_app.task(name=US_DEFINITION.celery_task_name)
@track_task(
    task_type=US_DEFINITION.task_type,
    task_name=US_DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=US_DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def run_market_structure_us(trade_date=None, start_date=None, end_date=None, **kwargs):
    return _run("US", trade_date, start_date, end_date)

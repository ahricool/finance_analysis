"""Scheduled aggregation without providers, previews, or strategy recalculation."""

from datetime import date
from finance_analysis.confluence.service import ConfluenceService
from finance_analysis.market_review.trading_calendar import (
    get_market_now,
    is_market_open,
    get_effective_trading_date,
    is_market_session_closed,
)
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import TaskSkipped, track_task


def _run(market, trade_date=None):
    now = get_market_now(market.lower())
    today = now.date()
    day = date.fromisoformat(trade_date) if trade_date else get_effective_trading_date(market.lower(), current_time=now)
    if day > today:
        raise ValueError("Future confluence dates are not supported")
    if not is_market_open(market.lower(), day):
        raise TaskSkipped("非交易日，跳过多信号共振")
    if not is_market_session_closed(market.lower(), current_time=now, check_date=day):
        raise TaskSkipped("交易日尚未收盘，跳过正式多信号共振")
    return ConfluenceService().run(market, day)


CN_DEFINITION = require_scheduled_task_definition("confluence_cn")


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
def run_confluence_cn(trade_date=None, **kwargs):
    return _run("CN", trade_date)


US_DEFINITION = require_scheduled_task_definition("confluence_us")


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
def run_confluence_us(trade_date=None, **kwargs):
    return _run("US", trade_date)

"""Tracked tasks sharing a single options mutex; holiday/early-close checks happen at execution."""

from finance_analysis.core.time import utc_now
from finance_analysis.options_intelligence.config import get_options_config
from finance_analysis.options_intelligence.service import OptionsIntelligenceService, session_context
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task, TaskSkipped
from finance_analysis.tasks.advisory_lock import TaskAdvisoryLockId

INTRADAY = require_scheduled_task_definition("options_intelligence_intraday")
DAILY = require_scheduled_task_definition("options_intelligence_daily")


def _scheduled(phase):
    config = get_options_config()
    if not config.enabled:
        raise TaskSkipped("期权分析已关闭")
    now = utc_now()
    day, current, _, close = session_context(now)
    from finance_analysis.market_review.trading_calendar import get_market_now

    if day != get_market_now("us", now).date() or current != phase:
        raise TaskSkipped("非对应美股交易时段")
    if phase == "daily" and (now - close).total_seconds() < 1800:
        raise TaskSkipped("等待盘后数据")
    return OptionsIntelligenceService(config=config).scan(view="preview" if phase == "intraday" else "official")


@celery_app.task(name=INTRADAY.celery_task_name)
@track_task(
    task_type=INTRADAY.task_type,
    task_name=INTRADAY.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=INTRADAY.job_id,
    advisory_lock_id=TaskAdvisoryLockId.OPTIONS_INTELLIGENCE,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def scan_options_intraday(**kwargs):
    return _scheduled("intraday")


@celery_app.task(name=DAILY.celery_task_name)
@track_task(
    task_type=DAILY.task_type,
    task_name=DAILY.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DAILY.job_id,
    advisory_lock_id=TaskAdvisoryLockId.OPTIONS_INTELLIGENCE,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def scan_options_daily(**kwargs):
    return _scheduled("daily")


@celery_app.task(name="options.request")
@track_task(
    task_type="options_intelligence",
    task_name="期权分析",
    source="celery_manual",
    advisory_lock_id=TaskAdvisoryLockId.OPTIONS_INTELLIGENCE,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def options_request(symbol=None, explain=False, view=None, trade_date=None, **kwargs):
    config = get_options_config()
    if not config.enabled:
        raise TaskSkipped("期权分析已关闭")
    service = OptionsIntelligenceService(config=config)
    if explain:
        from datetime import date

        return service.explain(symbol, date.fromisoformat(trade_date) if trade_date else None)
    return service.scan([symbol] if symbol else None, view=view)

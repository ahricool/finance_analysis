"""Close-only market sentiment observations with tracked readiness retries."""

from datetime import date

from finance_analysis.market_sentiment.service import MarketSentimentService
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError
from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open, is_market_session_closed
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.advisory_lock import TaskAdvisoryLockId
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task, TaskSkipped

DEFINITION = require_scheduled_task_definition("market_sentiment_cn")


@celery_app.task(
    name=DEFINITION.celery_task_name,
    autoretry_for=(FuyaoError, TimeoutError),
    retry_kwargs={"max_retries": 3},
    default_retry_delay=600,
)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
    advisory_lock_id=TaskAdvisoryLockId.CN_MARKET_SENTIMENT,
    advisory_lock_blocking=False,
)
def run_market_sentiment_cn(
    trade_date: str | None = None, backfill_days: int | None = None, missing_only: bool = True, **kwargs
):
    if trade_date is None and backfill_days is None and not is_market_open("cn", get_market_now("cn").date()):
        raise TaskSkipped("非 A 股交易日，跳过市场情绪")
    if trade_date is None and backfill_days is None and not is_market_session_closed("cn"):
        raise TaskSkipped("A 股尚未收盘，跳过市场情绪")
    return MarketSentimentService().run(
        date.fromisoformat(trade_date) if trade_date else None, backfill_days, missing_only
    )

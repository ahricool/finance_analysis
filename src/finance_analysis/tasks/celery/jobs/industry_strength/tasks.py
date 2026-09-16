"""Close-only industry observations with tracked readiness retries."""

from datetime import date

from finance_analysis.industry_strength.service import IndustryStrengthService, IndustryReadinessError
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError
from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.advisory_lock import TaskAdvisoryLockId
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import track_task, TaskSkipped

DEFINITION = require_scheduled_task_definition("industry_strength_cn")


@celery_app.task(
    name=DEFINITION.celery_task_name,
    autoretry_for=(IndustryReadinessError, FuyaoError),
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
    advisory_lock_id=TaskAdvisoryLockId.CN_INDUSTRY_STRENGTH,
    advisory_lock_blocking=False,
)
def run_industry_strength_cn(trade_date: str | None = None, **kwargs):
    if trade_date is None and not is_market_open("cn", get_market_now("cn").date()):
        raise TaskSkipped("非 A 股交易日，跳过行业强度")
    return IndustryStrengthService().run(date.fromisoformat(trade_date) if trade_date else None)

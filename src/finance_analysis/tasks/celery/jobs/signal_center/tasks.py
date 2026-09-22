"""Beat checks persisted readiness; no producer hooks or worker sleeps."""

from datetime import time
from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open, is_market_session_closed
from finance_analysis.signal_center.service import SignalCenterService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import TaskSkipped, track_task


def _run(market):
    now = get_market_now(market.lower())
    day = now.date()
    if not is_market_open(market.lower(), day) or not is_market_session_closed(
        market.lower(), current_time=now, check_date=day
    ):
        raise TaskSkipped("非交易日或尚未收盘，不生成当日正式信号")
    cutoff = time(21, 50) if market == "CN" else time(23, 50)
    result = SignalCenterService().run(market, day, deadline=now.time() >= cutoff)
    if result["status"] in {"waiting", "busy"}:
        raise TaskSkipped("等待当日正式来源就绪或同日任务完成；下次Beat主动检查")
    if result["status"] == "skipped":
        raise TaskSkipped(result.get("reason", "当天核心输入不足，已保存缺失快照"))
    return result


CN = require_scheduled_task_definition("signal_center_cn")
US = require_scheduled_task_definition("signal_center_us")


@celery_app.task(name=CN.celery_task_name)
@track_task(
    task_type=CN.task_type,
    task_name=CN.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=CN.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def run_signal_center_cn(**kwargs):
    return _run("CN")


@celery_app.task(name=US.celery_task_name)
@track_task(
    task_type=US.task_type,
    task_name=US.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=US.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def run_signal_center_us(**kwargs):
    return _run("US")

"""All strategies share one task; failed children never abort remaining evaluations."""

from finance_analysis.stock_strategies.service import StockStrategyService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import TaskExecutionStatus, TaskOutcome, TaskSkipped, track_task

DEFINITION = require_scheduled_task_definition("stock_strategies")


def outcome(result):
    if result["failed"]:
        return TaskOutcome(
            TaskExecutionStatus.PARTIAL if result["success"] else TaskExecutionStatus.FAILED,
            f"策略模拟：成功{result['success']}，失败{result['failed']}，等待{result['waiting']}",
        )
    if result["waiting"]:
        return TaskOutcome(TaskExecutionStatus.PARTIAL, f"等待数据的策略{result['waiting']}项；下次Beat继续")
    return None


@celery_app.task(name=DEFINITION.celery_task_name)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
    outcome_getter=outcome,
)
def run_stock_strategies(market=None, strategy_key=None, **kwargs):
    result = StockStrategyService().run(market=market, strategy_key=strategy_key)
    if not result["results"] or all(r["status"] == "busy" for r in result["results"]):
        raise TaskSkipped("策略均已结算、尚未进入盘后窗口或已有任务执行中")
    return result

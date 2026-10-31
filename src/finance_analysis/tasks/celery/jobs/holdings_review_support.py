"""Fan out one market tick into private per-user jobs before any model call."""

from finance_analysis.database.repositories.holdings_review import HoldingsReviewRepository
from finance_analysis.holdings_review.calendar import review_window
from finance_analysis.holdings_review.service import HoldingsReviewService
from finance_analysis.tasks.lifecycle import TaskSkipped, TaskOutcome, TaskExecutionStatus


def run_review(task, market, uid):
    if uid is not None:
        return HoldingsReviewService().run(market, uid=uid)
    window = review_window(market)
    if window is None:
        raise TaskSkipped("非交易日或尚未到达本市场收盘前50分钟")
    owners = HoldingsReviewRepository().user_ids(market)
    for owner in owners:
        task.apply_async(kwargs={"uid": owner, "owner_uid": owner, "_trigger_source": "scheduler"}, queue="analysis")
    return {"market": market, "dispatched": len(owners), "trade_date": window[0].date().isoformat()}


def review_outcome(result):
    if result.get("failed"):
        return TaskOutcome(
            TaskExecutionStatus.PARTIAL if result.get("completed") else TaskExecutionStatus.FAILED,
            "持仓复盘存在未完成的用户任务，请查看错误与复盘页面",
        )
    return None

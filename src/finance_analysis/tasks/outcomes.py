"""Business outcomes for explicitly opted-in batch/report task adapters."""

from collections import Counter
from typing import Any

from finance_analysis.tasks.lifecycle import TaskExecutionStatus, TaskOutcome


def analysis_batch_outcome(result: dict[str, Any]) -> TaskOutcome | None:
    failed = result["failed_count"]
    if not failed:
        return None
    status = TaskExecutionStatus.FAILED if failed == result["total_count"] else TaskExecutionStatus.PARTIAL
    return TaskOutcome(status, f"分析失败 {failed}/{result['total_count']}；详见任务日志")


def summarize_earnings_result(result: dict[str, Any]) -> dict[str, Any]:
    # Persist full aggregate counts before lifecycle detail truncation (MAX_JSON_ITEMS).
    counts = Counter(item["status"] for item in result["results"])
    return {**result, "total_count": len(result["results"]), "failed_count": counts["failed"],
            "status_counts": dict(counts)}


def earnings_batch_outcome(result: dict[str, Any]) -> TaskOutcome | None:
    failed = result["failed_count"]
    if not failed:
        return None
    status = TaskExecutionStatus.FAILED if failed == result["total_count"] else TaskExecutionStatus.PARTIAL
    return TaskOutcome(status, f"财报处理失败 {failed}/{result['total_count']}；详见事件状态和任务日志")


def market_sync_outcome(result: dict[str, Any]) -> TaskOutcome | None:
    if result["sync_status"] != "partial":
        return None
    return TaskOutcome(TaskExecutionStatus.PARTIAL,
                       f"日线同步部分失败：partial={result['partial_symbols']}, failed={result['failed_symbols']}")


def report_delivery_outcome(result: dict[str, Any]) -> TaskOutcome | None:
    failed = [channel for channel, sent in result.get("channel_results", {}).items() if not sent]
    if not failed:
        return None
    return TaskOutcome(TaskExecutionStatus.PARTIAL, "报告已生成，推送失败渠道：" + ", ".join(failed))

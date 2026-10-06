"""Business failures close lifecycle without retrying completed side effects."""

import json
from unittest.mock import Mock, patch

import pytest

from finance_analysis.tasks.lifecycle import TaskExecutionStatus, TaskLifecycleMetadata, TaskLifecycleService, track_task
from finance_analysis.tasks.outcomes import (
    analysis_batch_outcome, earnings_batch_outcome, market_sync_outcome,
    report_delivery_outcome, summarize_earnings_result,
)
from finance_analysis.database.repositories.task_record import TaskRecordRepository


@pytest.mark.parametrize("success,failed,status", [(0, 15, "failed"), (13, 2, "partial"), (15, 0, "completed")])
def test_batch_return_is_preserved_without_retry_or_second_notification(tmp_path, monkeypatch, success, failed, status):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    service = Mock()
    business = Mock(return_value={"total_count": 15, "success_count": success, "failed_count": failed})
    run = track_task(task_type="test", task_name="batch", source="celery",
                     outcome_getter=analysis_batch_outcome)(business)
    with patch("finance_analysis.tasks.lifecycle.get_task_lifecycle_service", return_value=service), \
            patch("finance_analysis.tasks.lifecycle._send_task_failure_notification") as notify:
        assert run() == business.return_value
    business.assert_called_once()
    notify.assert_not_called()
    if status == "completed":
        service.mark_completed.assert_called_once()
        service.mark_outcome.assert_not_called()
    else:
        service.mark_completed.assert_not_called()
        assert service.mark_outcome.call_args.kwargs["outcome"].status.value == status
        assert service.mark_outcome.call_args.kwargs["result"] is business.return_value


def test_earnings_full_counts_survive_detail_truncation():
    results = [{"status": "success", "event_id": i} for i in range(45)]
    results += [{"status": "failed", "event_id": i} for i in range(45, 50)]
    result = summarize_earnings_result({"stage": "daily", "results": results})
    outcome = earnings_batch_outcome(result)
    repository = Mock()
    service = TaskLifecycleService(repository=repository)
    service.mark_outcome(task_id="full-batch", metadata=TaskLifecycleMetadata("earnings", "earnings", "celery"),
                         outcome=outcome, result=result)
    stored = repository.update_status.call_args.kwargs
    summary = json.loads(stored["result"])
    assert summary["total_count"] == 50
    assert summary["failed_count"] == 5
    assert summary["status_counts"] == {"success": 45, "failed": 5}
    assert stored["status"] == "partial"
    assert stored["finished_at"] is not None
    assert stored["progress"] == 100
    assert not TaskRecordRepository._can_apply_status("partial", "pending")
    assert not TaskRecordRepository._can_apply_status("partial", "processing")


def test_expected_earnings_skips_and_market_fallbacks_are_not_failures():
    result = summarize_earnings_result({"results": [{"status": s} for s in ["frozen", "ineligible", "deferred"]]})
    assert earnings_batch_outcome(result) is None
    assert market_sync_outcome({"sync_status": "success", "fallback_reasons": ["provider unavailable"]}) is None
    outcome = market_sync_outcome({"sync_status": "partial", "partial_symbols": 5, "failed_symbols": 0})
    assert outcome.status == TaskExecutionStatus.PARTIAL
    assert report_delivery_outcome({"fallback_used": True, "warnings": ["LLM failed"],
                                    "channel_results": {"telegram": True, "ntfy": True}}) is None
    assert report_delivery_outcome({"channel_results": {"telegram": True, "ntfy": False}}).status.value == "partial"


def test_final_earnings_nontrading_day_is_an_expected_skip(monkeypatch):
    from finance_analysis.tasks.celery.jobs.earnings_outlook import tasks
    from finance_analysis.tasks.lifecycle import TaskSkipped
    monkeypatch.setattr(tasks, "EarningsOutlookService", lambda: Mock(
        run=Mock(return_value={"status": "skipped", "reason": "非美股交易日"})))
    with pytest.raises(TaskSkipped, match="非美股交易日"):
        tasks._run_outlook("final")

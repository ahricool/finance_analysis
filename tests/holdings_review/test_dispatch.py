from types import SimpleNamespace as NS
from datetime import datetime
from unittest.mock import Mock

from finance_analysis.tasks.celery.jobs import holdings_review_support as adapter


def test_market_tick_fans_out_before_any_llm_calls(monkeypatch):
    users = NS(user_ids=lambda market: [7, 8])
    monkeypatch.setattr(adapter, "HoldingsReviewRepository", lambda: users)
    monkeypatch.setattr(adapter, "review_window", lambda market: (datetime(2026, 10, 30), None, None))
    service = Mock()
    monkeypatch.setattr(adapter, "HoldingsReviewService", service)
    task = Mock()
    assert adapter.run_review(task, "CN", None)["dispatched"] == 2
    assert task.apply_async.call_count == 2
    assert task.apply_async.call_args_list[0].kwargs["kwargs"]["owner_uid"] == 7
    assert not service.called

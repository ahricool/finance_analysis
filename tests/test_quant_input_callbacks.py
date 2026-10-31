"""Prediction failures still finish business state when file cleanup needs a retry."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.transient import PredictionInputs
from finance_analysis.tasks.celery.jobs.quant_daily import tasks


@pytest.mark.parametrize("cleanup_error", (False, True))
def test_prediction_failure_reclaims_input_without_losing_failed_state(tmp_path, monkeypatch, cleanup_error):
    inputs = PredictionInputs(ArtifactStore(tmp_path))
    root = inputs.store.directory("temporary/example")
    (root / "manifest.json").write_text("{}")
    context = {"execution_id": "example", "input_uri": "quant://temporary/example", "market": "US"}
    repo = Mock()
    repo.execution.return_value = SimpleNamespace(status="predicting")
    monkeypatch.setattr(tasks, "QuantRepository", lambda: repo)
    monkeypatch.setattr(tasks, "PredictionInputs", lambda: inputs)
    monkeypatch.setattr(tasks.celery_app, "AsyncResult", lambda _id: SimpleNamespace(result="prediction failed"))
    finish = Mock()
    monkeypatch.setattr(tasks, "_mark_final_status", finish)
    if cleanup_error:
        monkeypatch.setattr(inputs, "remove", Mock(side_effect=PermissionError("retry cleanup")))
    result = tasks.fail_quant_daily.run("worker-id", context=context)
    assert result["status"] == "failed"
    updates = repo.update_execution.call_args.kwargs
    assert updates["status"] == "failed"
    assert updates["input_uri"] == (context["input_uri"] if cleanup_error else None)
    assert root.exists() is cleanup_error
    assert isinstance(finish.call_args.kwargs["error"], RuntimeError)


def test_failed_finalize_cleans_input_after_callback_retries_are_exhausted(tmp_path, monkeypatch):
    inputs = PredictionInputs(ArtifactStore(tmp_path))
    root = inputs.store.directory("temporary/example")
    (root / "manifest.json").write_text("{}")
    repo = Mock()
    pipeline = SimpleNamespace(finalize=Mock(side_effect=ValueError("publication failed")))
    monkeypatch.setattr(tasks, "QuantDailyPipeline", lambda: pipeline)
    monkeypatch.setattr(tasks, "QuantRepository", lambda: repo)
    monkeypatch.setattr(tasks, "PredictionInputs", lambda: inputs)
    monkeypatch.setattr(tasks, "_mark_final_status", Mock())
    callback = tasks.finalize_quant_daily
    callback.push_request(retries=callback.max_retries)
    try:
        with pytest.raises(ValueError, match="publication failed"):
            callback.run({}, context={"execution_id": "example", "input_uri": "quant://temporary/example"})
    finally:
        callback.pop_request()
    assert not root.exists()
    assert repo.update_execution.call_args.kwargs["status"] == "failed"
    assert repo.update_execution.call_args.kwargs["input_uri"] is None

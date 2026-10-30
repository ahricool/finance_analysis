"""Timing must survive fallback, thread pools, failures and report serialization."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from unittest.mock import Mock

import pytest

from finance_analysis.llm import LLMClient, LLMError, LLMRequest, LLMResult
from finance_analysis.llm import api, remote_cli
from finance_analysis.llm.config import LLMConfig, get_llm_config
from finance_analysis.llm.timing import CURRENT_TIMINGS, TimingCollector, append_timings, timing_rows
from finance_analysis.tasks.lifecycle import _result_with_timings


@pytest.fixture
def scope():
    token = CURRENT_TIMINGS.set(TimingCollector())
    try:
        yield CURRENT_TIMINGS.get()
    finally:
        CURRENT_TIMINGS.reset(token)


@pytest.fixture
def client(tmp_path, monkeypatch):
    client = LLMClient(
        LLMConfig(log_dir=tmp_path, cli_ssh_username="u", cli_ssh_password="secret", model="test", api_key="secret")
    )
    monkeypatch.setattr(client, "_record", Mock())
    return client


def test_retries_have_fresh_300s_budget_without_total_deadline(client, monkeypatch, scope):
    now = [0.0]
    monkeypatch.setattr("finance_analysis.llm.client.time.monotonic", lambda: now[0])
    monkeypatch.setattr("finance_analysis.core.retry.sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    calls = []

    def cli(config, request):
        calls.append(request.timeout)
        now[0] += 290
        raise ConnectionError()

    def fallback(config, request):
        assert request.timeout == 300
        now[0] += 20
        return LLMResult("answer", "api")

    monkeypatch.setattr(remote_cli, "complete", cli)
    monkeypatch.setattr(api, "complete", fallback)
    result = client.complete_text(LLMRequest("private prompt", call_type="research", timeout=1))
    assert calls == [300] * 4
    assert result.text == "answer"
    row = timing_rows()[0]
    assert row["duration_ms"] == 1194000
    assert row["retry_wait_ms"] == 14000
    assert len(row["attempts"]) == 5
    assert row["attempts"][-1]["provider"] == "api"
    assert result.timing["duration_ms"] == row["duration_ms"]
    assert "private prompt" not in append_timings("report")
    assert "connection_failed" in append_timings("report")
    assert "api" in append_timings("report")


def test_failed_request_keeps_timing_and_report(client, monkeypatch, scope):
    monkeypatch.setattr(remote_cli, "complete", Mock(side_effect=TimeoutError()))
    monkeypatch.setattr(api, "complete", Mock(side_effect=TimeoutError()))
    with pytest.raises(LLMError):
        client.complete_text(LLMRequest("secret", call_type="forecast"))
    result = json.loads(_result_with_timings(None))
    assert [a["status"] for a in result["llm_timings"][0]["attempts"]] == ["timeout", "timeout"]
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("api_first", [False, True])
@pytest.mark.parametrize("primary_fails", [False, True])
def test_request_provider_order_and_fallback(client, monkeypatch, api_first, primary_fails):
    client.config = replace(client.config, max_retries=0)
    order = ["api", "codex"] if api_first else ["codex", "api"]
    calls = []

    def complete(provider):
        def call(*args):
            calls.append(provider)
            if primary_fails and provider == order[0]:
                raise TimeoutError()
            return LLMResult("answer", "api" if provider == "api" else "cli", engine=provider)

        return call

    monkeypatch.setattr(api, "complete", complete("api"))
    monkeypatch.setattr(remote_cli, "complete", complete("codex"))
    result = client.complete_text(LLMRequest("prompt", api_first=api_first))
    assert calls == (order if primary_fails else order[:1])
    assert [a["provider"] for a in result.attempts] == calls


def test_api_first_skips_unconfigured_api(client, monkeypatch):
    client.config = replace(client.config, api_key="")
    api_call = Mock()
    monkeypatch.setattr(api, "complete", api_call)
    monkeypatch.setattr(remote_cli, "complete", lambda *args: LLMResult("answer", "cli", engine="codex"))
    result = client.complete_text(LLMRequest("prompt", api_first=True))
    api_call.assert_not_called()
    assert [(a["provider"], a["status"]) for a in result.attempts] == [
        ("api", "not_configured"),
        ("codex", "success"),
    ]


def test_copied_threads_share_collector_and_scopes_are_isolated(client, monkeypatch, scope):
    monkeypatch.setattr(remote_cli, "complete", lambda *a: LLMResult("ok", "cli"))
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(copy_context().run, client.complete_text, LLMRequest("p", uid=uid)) for uid in (1, 2)]
        for future in futures:
            future.result()
    assert len(timing_rows()) == 2
    assert len(timing_rows(uid=1)) == 1
    token = CURRENT_TIMINGS.set(TimingCollector())
    try:
        assert append_timings("another task") == "another task"
    finally:
        CURRENT_TIMINGS.reset(token)


def test_timings_not_truncated_with_large_business_payload(scope):
    for index in range(80):
        scope.add(dict(request_id=str(index), call_type="test", attempts=[], duration_ms=0, retry_wait_ms=0))
    payload = json.loads(_result_with_timings({"data": ["x" * 2000] * 100}))
    assert len(payload["llm_timings"]) == 80


def test_env_route_is_fixed_and_old_total_budget_ignored(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("LLM_TIMEOUT", "1")
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUT", "300")
    get_llm_config.cache_clear()
    try:
        config = get_llm_config()
        assert [(p.backend, p.cli_engine) for p in config.providers()] == [("cli", "codex"), ("api", "codex")]
        assert not hasattr(config, "timeout")
        assert config.attempt_timeout == 300
    finally:
        get_llm_config.cache_clear()


def test_rendered_stock_report_carries_saved_timings():
    from finance_analysis.analysis.stock_report_analyzer import AnalysisResult
    from finance_analysis.notification.service import NotificationService

    result = AnalysisResult(
        code="A.US",
        name="A",
        sentiment_score=50,
        trend_prediction="震荡",
        operation_advice="持有",
        llm_timings=[
            dict(
                request_id="12345678",
                call_type="stock_analysis",
                duration_ms=320000,
                retry_wait_ms=0,
                attempts=[
                    dict(provider="codex", attempt=1, duration_ms=300000, status="timeout"),
                    dict(provider="api", attempt=1, duration_ms=20000, status="success"),
                ],
            )
        ],
    )
    # Rendering does not require external channels or a running collector.
    notifier = NotificationService.__new__(NotificationService)
    report = notifier.generate_single_stock_report(result=result)
    assert "LLM 调用耗时" in report
    assert "300.00s（timeout）" in report and "20.00s（success）" in report
    assert result.to_dict()["llm_timings"] == result.llm_timings


@pytest.mark.parametrize("failed", [False, True])
def test_task_lifecycle_persists_attempts_and_releases_scope(client, monkeypatch, tmp_path, failed):
    from contextlib import nullcontext
    from finance_analysis.tasks import lifecycle

    repo = Mock()
    service = lifecycle.TaskLifecycleService(repository=repo)
    monkeypatch.setattr(lifecycle, "get_task_lifecycle_service", lambda: service)
    monkeypatch.setattr(lifecycle, "task_logging_context", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(lifecycle, "_relative_task_log_path", lambda *a, **kw: "unit.log")
    monkeypatch.setattr(lifecycle, "_send_task_failure_notification", Mock())
    monkeypatch.setattr(
        remote_cli,
        "complete",
        Mock(side_effect=TimeoutError()) if failed else Mock(return_value=LLMResult("ok", "cli")),
    )
    monkeypatch.setattr(api, "complete", Mock(side_effect=TimeoutError()))

    @lifecycle.track_task(task_type="unit", task_name="unit", source="celery")
    def run():
        client.complete_text(LLMRequest("private", call_type="test"))
        return {"status": "success"}

    assert CURRENT_TIMINGS.get() is None
    if failed:
        with pytest.raises(LLMError):
            run()
    else:
        assert run() == {"status": "success"}
    assert CURRENT_TIMINGS.get() is None
    final = repo.update_status.call_args.kwargs
    assert final["status"] == ("failed" if failed else "completed")
    assert len(json.loads(final["result"])["llm_timings"]) == 1


def test_notification_saved_and_pushed_report_filters_other_users(scope):
    from finance_analysis.notification.service import NotificationService

    for uid in (1, 2):
        scope.add(
            dict(
                uid=uid,
                request_id=f"user{uid}request",
                call_type=f"user{uid}",
                attempts=[dict(provider="codex", attempt=1, duration_ms=10, status="success")],
                duration_ms=10,
                retry_wait_ms=0,
            )
        )
    notifier = NotificationService.__new__(NotificationService)
    notifier.persist = Mock(return_value=12)
    notifier._push_message = Mock()
    notifier.send("Report", uid=1, push_content="Push summary")
    saved = notifier.persist.call_args.args[0]
    pushed = notifier._push_message.call_args.args[1]
    for content in (saved, pushed):
        assert "LLM 调用耗时" in content and "user1" in content and "user2" not in content
    # Already persisted trade messages must not acquire other users' timing at push time.
    notifier.push_existing(saved, notification_id=12)
    assert notifier._push_message.call_args.args[1] == saved


def test_timing_does_not_change_notification_dedup_content():
    from types import SimpleNamespace
    from finance_analysis.notification.service import NotificationService, NotificationResult

    notifier = NotificationService.__new__(NotificationService)
    notifier._available_channels = ["test"]
    notifier.get_channels_for_route = Mock(return_value=["test"])
    notifier.evaluate_noise_control = Mock(return_value=SimpleNamespace(should_send=False, message="duplicate"))
    for request_id in ("first", "second"):
        notifier._push_message(
            NotificationResult(notification_id=1),
            f"Report\n\n### LLM 调用耗时\n{request_id}",
            route_type=None,
            severity=None,
            dedup_key=None,
            cooldown_key=None,
        )
        assert notifier.evaluate_noise_control.call_args.args[0] == "Report"

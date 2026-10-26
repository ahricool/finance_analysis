"""Provider order, bounded retries, clock budgets and safe provenance."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from finance_analysis.llm import LLMClient, LLMError, LLMRequest, LLMResult
from finance_analysis.llm import api, remote_cli
from finance_analysis.llm.config import LLMConfig, get_llm_config
from finance_analysis.llm.failures import ProviderFailure, classify_exception


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from finance_analysis.database import DatabaseManager
    from finance_analysis.llm import client
    from finance_analysis.core import retry

    db = MagicMock()
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: db)
    now = [0.0]
    waits = []
    monkeypatch.setattr(client.time, "monotonic", lambda: now[0])

    def wait(seconds):
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(retry, "sleep", wait)
    monkeypatch.setattr(client.time, "sleep", wait)
    config = LLMConfig(
        log_dir=tmp_path,
        cli_ssh_username="u",
        cli_ssh_password="private-ssh",
        api_key="private-api",
        model="openai/api-test",
        codex_model="codex-test",
    )
    calls = []
    failures = {}

    def call(config, request):
        name = config.cli_engine if config.backend == "cli" else "api"
        calls.append((name, config, request))
        error = failures.get(name)
        if callable(error):
            error = error(request)
        if error:
            raise error
        return LLMResult(
            '{"ok":true}',
            config.backend,
            engine=config.cli_engine if name != "api" else None,
            model=config.cli_model if name != "api" else config.model,
        )

    monkeypatch.setattr(remote_cli, "complete", call)
    monkeypatch.setattr(api, "complete", call)
    return SimpleNamespace(config=config, calls=calls, failures=failures, now=now, waits=waits, db=db)


@pytest.mark.parametrize("success,expected", [("codex", ["codex"]), ("api", ["codex", "api"])])
def test_order_and_actual_model(ctx, success, expected):
    for name in expected[:-1]:
        ctx.failures[name] = ProviderFailure("quota_exhausted")
    request = LLMRequest("immutable snapshot", system_prompt="same system", uid=7)
    result = LLMClient(ctx.config).complete_text(request, validator=json.loads)
    assert [c[0] for c in ctx.calls] == expected
    assert result.model == ("openai/api-test" if success == "api" else success + "-test")
    assert ctx.waits == []
    assert all(c[2].prompt == request.prompt and c[2].system_prompt == request.system_prompt for c in ctx.calls)
    rows = [json.loads(line) for line in next(ctx.config.log_dir.glob("*.log")).read_text().splitlines()]
    assert len({r["request_id"] for r in rows}) == 1
    assert [r["engine"] or r["backend"] for r in rows] == expected
    assert rows[-1]["model"] == result.model
    assert ctx.db.record_llm_usage.call_count == len(expected)
    ctx.db.connect.assert_not_called()


def test_three_retries_per_provider_with_248_backoff(ctx):
    ctx.failures.update({name: ConnectionError("credential") for name in ("codex", "api")})
    with pytest.raises(LLMError, match="api:connection_failed"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert [c[0] for c in ctx.calls] == ["codex"] * 4 + ["api"] * 4
    assert ctx.waits == [2, 4, 8] * 2


def test_timeout_switches_and_preserves_later_budgets(ctx):
    def timeout(request):
        ctx.now[0] += request.timeout
        return ProviderFailure("timeout")

    ctx.failures.update(codex=timeout, api=timeout)
    with pytest.raises(LLMError, match="api:timeout"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert [c[0] for c in ctx.calls] == ["codex", "api"]
    assert [c[2].timeout for c in ctx.calls] == [300, 300]
    assert ctx.now[0] == 600
    assert ctx.waits == []


def test_unconfigured_api_is_audited_without_usage(ctx):
    ctx.failures.update(codex=TimeoutError())
    with pytest.raises(LLMError, match="api:not_configured"):
        LLMClient(replace(ctx.config, api_key="")).complete_text(LLMRequest("prompt"))
    assert ctx.db.record_llm_usage.call_count == 1
    rows = [json.loads(line) for line in next(ctx.config.log_dir.glob("*.log")).read_text().splitlines()]
    assert rows[-1]["status"] == "skipped"


@pytest.mark.parametrize(
    "error",
    [
        TypeError("secret"),
        ProviderFailure("cleanup_unconfirmed", fatal=True),
    ],
)
def test_fatal_failures_do_not_switch(ctx, error):
    ctx.failures["codex"] = error
    with pytest.raises(LLMError) as exc:
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert len(ctx.calls) == 1
    assert "secret" not in str(exc.value)


def test_invalid_output_retries_then_switches(ctx):
    count = [0]

    def validator(_):
        count[0] += 1
        if count[0] <= 4:
            raise ValueError("private invalid result")

    result = LLMClient(ctx.config).complete_text(LLMRequest("prompt"), validator=validator)
    assert result.backend == "api"
    assert [c[0] for c in ctx.calls] == ["codex"] * 4 + ["api"]
    assert ctx.waits == [2, 4, 8]


@pytest.mark.parametrize(
    "status,message,code,retryable,fatal",
    [
        (429, "Individual quota reached", "quota_exhausted", False, False),
        (429, "rate limited", "rate_limited", True, False),
        (401, "private-key", "authentication_failed", False, False),
        (404, "no model", "model_unavailable", False, False),
        (503, "private-key", "service_unavailable", True, False),
        (400, "bad request", "invalid_request", False, True),
    ],
)
def test_error_classification(status, message, code, retryable, fatal):
    error = RuntimeError(message)
    error.status_code = status
    failure = classify_exception(error)
    assert (failure.code, failure.retryable, failure.fatal) == (code, retryable, fatal)
    assert "private-key" not in str(failure)


def test_validator_programming_error_does_not_retry(ctx):
    def validator(_):
        raise TypeError("programming mistake")

    with pytest.raises(LLMError, match="internal_error"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"), validator=validator)
    assert len(ctx.calls) == 1
    assert ctx.waits == []


def test_payment_required_is_not_retried_and_audit_has_budgets(ctx):
    class PaymentRequired(Exception):
        status_code = 402

    ctx.failures.update(codex=ProviderFailure("timeout"), api=PaymentRequired("private-api billing details"))
    with pytest.raises(LLMError, match="api:insufficient_credits"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert len(ctx.calls) == 2
    assert ctx.waits == []
    content = next(ctx.config.log_dir.glob("*.log")).read_text()
    rows = [json.loads(line) for line in content.splitlines()]
    assert rows[-1]["error"] == "insufficient_credits"
    assert "total_budget_ms" not in rows[0]["diagnostics"]
    assert rows[0]["diagnostics"]["attempt_budget_ms"] == 300000
    assert "billing details" not in content


def test_payment_required_falls_back_without_retry(ctx):
    error = RuntimeError("private billing message")
    error.status_code = 402
    ctx.failures["codex"] = error
    assert LLMClient(ctx.config).complete_text(LLMRequest("prompt")).backend == "api"
    assert [call[0] for call in ctx.calls] == ["codex", "api"]
    assert ctx.waits == []
    content = next(ctx.config.log_dir.glob("*.log")).read_text()
    assert json.loads(content.splitlines()[0])["error"] == "insufficient_credits"
    assert "private billing message" not in content

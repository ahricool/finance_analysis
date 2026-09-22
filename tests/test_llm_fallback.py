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
    db.connect.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value = True
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
        fallback_chain="agy,codex,api",
        timeout=600,
        log_dir=tmp_path,
        cli_ssh_username="u",
        cli_ssh_password="private-ssh",
        api_key="private-api",
        model="openai/api-test",
        agy_model="agy-test",
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


@pytest.mark.parametrize(
    "success,expected", [("agy", ["agy"]), ("codex", ["agy", "codex"]), ("api", ["agy", "codex", "api"])]
)
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
    assert ctx.db.connect.call_count == sum(name != "api" for name in expected)


def test_three_retries_per_provider_with_248_backoff(ctx):
    ctx.failures.update({name: ConnectionError("credential") for name in ("agy", "codex", "api")})
    with pytest.raises(LLMError, match="api:connection_failed"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert [c[0] for c in ctx.calls] == ["agy"] * 4 + ["codex"] * 4 + ["api"] * 4
    assert ctx.waits == [2, 4, 8] * 3


def test_timeout_switches_and_preserves_later_budgets(ctx):
    def timeout(request):
        ctx.now[0] += request.timeout
        return ProviderFailure("timeout")

    ctx.failures.update(agy=timeout, codex=timeout, api=timeout)
    with pytest.raises(LLMError, match="api:timeout"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert [c[0] for c in ctx.calls] == ["agy", "codex", "api"]
    assert [c[2].timeout for c in ctx.calls] == [180, 180, 180]
    assert ctx.now[0] == 540
    assert ctx.waits == []


def test_short_override_allocates_budget_to_all_providers(ctx):
    def timeout(request):
        ctx.now[0] += request.timeout
        return TimeoutError()

    ctx.failures.update(agy=timeout, codex=timeout, api=timeout)
    with pytest.raises(LLMError):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt", timeout=90))
    assert [c[2].timeout for c in ctx.calls] == [30, 30, 30]
    assert ctx.now[0] == 90


def test_retry_cannot_consume_fallback_reserve(ctx):
    def temporary(request):
        ctx.now[0] += request.timeout
        return ConnectionError()

    ctx.failures["agy"] = temporary
    LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert [c[0] for c in ctx.calls] == ["agy", "agy", "codex"]
    assert [c[2].timeout for c in ctx.calls] == [180, 58, 180]
    assert ctx.waits == [2]


def test_unconfigured_api_is_audited_without_usage(ctx):
    ctx.failures.update(agy=TimeoutError(), codex=TimeoutError())
    with pytest.raises(LLMError, match="api:not_configured"):
        LLMClient(replace(ctx.config, api_key="")).complete_text(LLMRequest("prompt"))
    assert ctx.db.record_llm_usage.call_count == 2
    rows = [json.loads(line) for line in next(ctx.config.log_dir.glob("*.log")).read_text().splitlines()]
    assert rows[-1]["status"] == "skipped"


@pytest.mark.parametrize(
    "error",
    [
        TypeError("secret"),
        ProviderFailure("cleanup_unconfirmed", fatal=True),
        ProviderFailure("lock_wait_timeout", fatal=True),
    ],
)
def test_fatal_failures_do_not_switch(ctx, error):
    ctx.failures["agy"] = error
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
    assert result.engine == "codex"
    assert [c[0] for c in ctx.calls] == ["agy"] * 4 + ["codex"]
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


def test_retry_after_is_bounded_by_stage_budget(ctx):
    ctx.failures["agy"] = ProviderFailure("rate_limited", retryable=True, retry_after=300)
    assert LLMClient(ctx.config).complete_text(LLMRequest("prompt")).engine == "codex"
    assert ctx.waits == []


def test_separate_model_settings_and_env(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_CHAIN", "agy,codex,api")
    monkeypatch.setenv("LLM_AGY_MODEL", "gemini")
    monkeypatch.setenv("LLM_CODEX_MODEL", "codex")
    monkeypatch.setenv("LLM_CLI_MODEL", "legacy-must-not-leak")
    monkeypatch.setenv("LLM_TIMEOUT", "600")
    get_llm_config.cache_clear()
    try:
        config = get_llm_config()
        assert [c.cli_model for c in config.providers()[:2]] == ["gemini", "codex"]
        assert config.timeout == 600
    finally:
        get_llm_config.cache_clear()


def test_lock_connection_failure_never_falls_back_to_api(ctx):
    ctx.db.connect.side_effect = ConnectionError("private database details")
    with pytest.raises(LLMError, match="lock_unavailable"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert ctx.calls == []
    assert ctx.waits == []


def test_validator_programming_error_does_not_retry(ctx):
    def validator(_):
        raise TypeError("programming mistake")

    with pytest.raises(LLMError, match="internal_error"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"), validator=validator)
    assert len(ctx.calls) == 1
    assert ctx.waits == []

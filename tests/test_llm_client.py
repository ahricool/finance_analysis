"""Offline API/SSH boundaries, one retry budget and credential-safe auditing."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import paramiko
import pytest

from finance_analysis.llm import LLMClient, LLMError, LLMRequest, LLMResult
from finance_analysis.llm import api, remote_cli
from finance_analysis.llm.config import LLMConfig, get_llm_config


@pytest.fixture
def config(tmp_path, monkeypatch):
    from finance_analysis.database import DatabaseManager

    db = Mock()
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: db)
    return LLMConfig(model="openai/test", api_key="private-api-secret", log_dir=tmp_path)


@pytest.mark.parametrize("backend", ["api", "cli"])
@pytest.mark.parametrize("failures", [0, 1, 2])
def test_attempt_budget_and_no_backend_fallback(config, monkeypatch, backend, failures):
    config = replace(
        config,
        backend=backend,
        cli_ssh_username="test",
        cli_ssh_password="private-ssh-secret",
    )
    result = LLMResult("ok", backend, model="test")
    call = Mock(side_effect=[RuntimeError("private-api-secret Authorization: Bearer x")] * failures + [result])
    other = Mock(side_effect=AssertionError("Must not switch backend"))
    monkeypatch.setattr(api if backend == "api" else remote_cli, "complete", call)
    monkeypatch.setattr(remote_cli if backend == "api" else api, "complete", other)
    client = LLMClient(config)
    request = LLMRequest("quoted '$()' 财经\n{}", system_prompt="system", uid=7)
    if failures == 2:
        with pytest.raises(LLMError) as error:
            client.complete_text(request)
        assert "private" not in str(error.value)
    else:
        assert client.complete_text(request).text == "ok"
    assert call.call_count == min(failures + 1, 2)
    other.assert_not_called()
    log = next(config.log_dir.glob("*.log")).read_text()
    assert "private-api-secret" not in log
    rows = [json.loads(line) for line in log.splitlines()]
    assert [r["attempt"] for r in rows] == list(range(1, len(rows) + 1))
    assert len({r["request_id"] for r in rows}) == 1
    assert rows[0]["prompt"] == request.prompt
    assert rows[0]["backend"] == backend
    from finance_analysis.database import DatabaseManager

    assert DatabaseManager.get_instance().record_llm_usage.call_count == len(rows)
    assert DatabaseManager.get_instance().record_llm_usage.call_args.kwargs["uid"] == 7


def test_api_conversion_and_sdk_retries_disabled(config, monkeypatch):
    import litellm

    call = Mock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="response"))],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        )
    )
    monkeypatch.setattr(litellm, "completion", call)
    result = api.complete(config, LLMRequest("user", system_prompt="system", max_tokens=100))
    assert result.usage == dict(input_tokens=2, output_tokens=3, total_tokens=5)
    assert result.text == "response" and result.model == config.model
    assert call.call_args.kwargs["num_retries"] == 0
    assert call.call_args.kwargs["messages"] == [
        dict(role="system", content="system"),
        dict(role="user", content="user"),
    ]
    call.return_value = {"choices": [{"message": {"content": [{"text": "part"}]}}]}
    assert api.complete(config, LLMRequest("user")).text == "part"
    call.return_value = {"choices": []}
    with pytest.raises(ValueError, match="empty"):
        api.complete(config, LLMRequest("user"))


def test_json_validation_consumes_same_retry_budget(config, monkeypatch):
    call = Mock(side_effect=[LLMResult("invalid", "api"), LLMResult("{}", "api")])
    monkeypatch.setattr(api, "complete", call)
    assert LLMClient(config).complete_text(LLMRequest("json"), validator=json.loads).text == "{}"
    assert call.call_count == 2
    rows = [json.loads(line) for line in next(config.log_dir.glob("*.log")).read_text().splitlines()]
    assert rows[0]["status"] == "failed" and rows[0]["response"] == "invalid"


def test_no_retry_after_deadline(config, monkeypatch):
    clock = Mock(side_effect=[0, 0, 0, 181, 181])
    monkeypatch.setattr("finance_analysis.llm.client.time.monotonic", clock)
    call = Mock(side_effect=TimeoutError())
    monkeypatch.setattr(api, "complete", call)
    with pytest.raises(LLMError):
        LLMClient(config).complete_text(LLMRequest("prompt"))
    assert call.call_count == 1


@pytest.mark.parametrize("backend", ["api", "cli"])
def test_env_backend(monkeypatch, backend):
    monkeypatch.setenv("LLM_BACKEND", backend)
    get_llm_config.cache_clear()
    assert get_llm_config().backend == backend
    get_llm_config.cache_clear()


@pytest.mark.parametrize(
    "kwargs",
    [{"backend": "other"}, {"cli_engine": "other"}, {"max_retries": 2}, {"timeout": 0}],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        LLMConfig(**kwargs)


AGY = json.dumps(
    dict(
        event="result",
        result=dict(
            status="SUCCESS",
            response="answer",
            usage=dict(input_tokens=4, output_tokens=5, total_tokens=9),
        ),
    )
)


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "{}",
        "{",
        '{"status":"FAILED","error":"credential"}',
        '{"status":"SUCCESS","response":""}',
    ],
)
def test_agy_failure(stdout):
    with pytest.raises(ValueError):
        remote_cli.parse_agy(stdout)


def test_agy_json():
    result = remote_cli.parse_agy(AGY)
    assert result.text == "answer" and result.usage["total_tokens"] == 9
    assert result.model is None


def test_codex_jsonl():
    events = [
        dict(type="thread.started"),
        dict(type="item.completed", item=dict(type="agent_message", text="earlier")),
        dict(type="item.completed", item=dict(type="agent_message", text="final")),
        dict(
            type="turn.completed",
            usage=dict(input_tokens=10, cached_input_tokens=8, output_tokens=2),
        ),
    ]
    result = remote_cli.parse_codex("\n".join(map(json.dumps, events)))
    assert result.text == "final" and result.usage["total_tokens"] == 12


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        "{}",
        '{"type":"error"}',
        '{"type":"turn.failed"}',
        '{"type":"item.completed"}',
        '{"type":"turn.started"}',
    ],
)
def test_codex_failure(text):
    with pytest.raises(ValueError):
        remote_cli.parse_codex(text)


class Channel:
    def __init__(self, output=AGY, status=0, hanging=False):
        self.output = output.encode()
        self.status = status
        self.hanging = hanging
        self.input = bytearray()
        self.command = ""
        self.eof = self.closed = False
        self.err = b"diagnostic secret"

    def settimeout(self, timeout):
        pass

    def exec_command(self, command):
        self.command = command

    def send_ready(self):
        return True

    def send(self, data):
        self.input.extend(data[:37])
        return len(data[:37])

    def shutdown_write(self):
        self.eof = True

    def recv_ready(self):
        return self.eof and bool(self.output)

    def recv(self, size):
        result, self.output = self.output[:size], self.output[size:]
        return result

    def recv_stderr_ready(self):
        return bool(self.err)

    def recv_stderr(self, size):
        result, self.err = self.err, b""
        return result

    def exit_status_ready(self):
        return self.eof and not self.hanging

    def recv_exit_status(self):
        return self.status

    def close(self):
        self.closed = True


def ssh_client(monkeypatch, channel, error=None):
    client = Mock()
    client.get_transport.return_value.open_session.return_value = channel
    client.connect.side_effect = error
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    return client


def test_ssh_stdin_and_command(config, monkeypatch):
    channel = Channel()
    client = ssh_client(monkeypatch, channel)
    prompt = '中文 "quotes" \' $() `touch /tmp/never`\n{}'
    config = replace(config, backend="cli", cli_ssh_username="user", cli_ssh_password="password")
    result = remote_cli.complete(config, LLMRequest(prompt, system_prompt="system"))
    assert result.text == "answer"
    assert json.loads(bytes(channel.input))["message"]["content"] == "system\n\n---\n\n" + prompt
    assert prompt not in channel.command
    assert "--input-format stream-json" in channel.command and "--sandbox" in channel.command
    assert "/tmp/finance-analysis-llm" in channel.command
    assert channel.closed
    client.close.assert_called_once()
    assert client.connect.call_args.kwargs["allow_agent"] is False
    assert isinstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.RejectPolicy)


@pytest.mark.parametrize("error", [paramiko.AuthenticationException(), paramiko.SSHException(), OSError()])
def test_ssh_connection_errors_close(config, monkeypatch, error):
    client = ssh_client(monkeypatch, Channel(), error)
    with pytest.raises(type(error)):
        remote_cli.complete(config, LLMRequest("prompt"))
    client.close.assert_called_once()


@pytest.mark.parametrize(
    "channel,exception",
    [
        (Channel(status=1), RuntimeError),
        (Channel(output=""), ValueError),
        (Channel(hanging=True), TimeoutError),
    ],
)
def test_ssh_execution_failures(config, monkeypatch, channel, exception):
    client = ssh_client(monkeypatch, channel)
    with pytest.raises(exception):
        remote_cli.complete(config, LLMRequest("prompt", timeout=0.05))
    assert channel.closed
    client.close.assert_called_once()


def test_codex_command(config):
    command = remote_cli.build_command(replace(config, cli_engine="codex", cli_effort="high"), 180)
    assert "codex exec --json" in command and "--sandbox read-only" in command and command.endswith(" -")
    assert "dangerously" not in command


def test_retry_disabled_and_log_secrets_redacted(config, monkeypatch):
    config = replace(config, max_retries=0, cli_ssh_password="ssh-secret")
    call = Mock(side_effect=RuntimeError("Authorization: Bearer private-api-secret"))
    monkeypatch.setattr(api, "complete", call)
    with pytest.raises(LLMError):
        LLMClient(config).complete_text(LLMRequest("private-api-secret\nAuthorization: Bearer token\nssh-secret"))
    assert call.call_count == 1
    raw = next(config.log_dir.glob("*.log")).read_text()
    row = json.loads(raw)
    assert row["status"] == "failed"
    assert all(secret not in raw for secret in ["private-api-secret", "ssh-secret", "Bearer token"])


def test_audit_and_usage_failure_never_retries_success(config, monkeypatch):
    config.log_dir.joinpath("not-directory").write_text("file")
    config = replace(config, log_dir=config.log_dir / "not-directory")
    call = Mock(return_value=LLMResult("ok", "api"))
    monkeypatch.setattr(api, "complete", call)
    from finance_analysis.database import DatabaseManager

    DatabaseManager.get_instance().record_llm_usage.side_effect = RuntimeError("db unavailable")
    assert LLMClient(config).complete_text(LLMRequest("prompt")).text == "ok"
    assert call.call_count == 1


def test_agy_failure_envelope_and_missing_tokens():
    failed = json.dumps(dict(event="result", result=dict(status="ERROR", response="secret diagnostic")))
    with pytest.raises(ValueError, match="failed status"):
        remote_cli.parse_agy(failed)
    empty = json.dumps(dict(event="result", result=dict(status="SUCCESS", response="")))
    with pytest.raises(ValueError, match="empty"):
        remote_cli.parse_agy(empty)
    success = json.dumps(dict(event="result", result=dict(status="SUCCESS", response="ok")))
    assert remote_cli.parse_agy(success).usage == dict(input_tokens=0, output_tokens=0, total_tokens=0)
    with pytest.raises(ValueError, match="multiple"):
        remote_cli.parse_agy(success + "\n" + success)


def test_long_unicode_prompt_stays_on_ssh_stdin(config, monkeypatch):
    channel = Channel()

    # Large chunks keep the fake fast while exceeding common OS argument limits.
    def send(data):
        channel.input.extend(data)
        return len(data)

    channel.send = send
    ssh_client(monkeypatch, channel)
    prompt = ('中文\n"quotes" $() `shell` ' * 10000) + "\n\n"
    remote_cli.complete(config, LLMRequest(prompt, timeout=5))
    assert json.loads(channel.input)["message"]["content"] == prompt
    assert len(channel.command) < 500


def test_stock_analyzer_uses_shared_client_and_preserves_owner(config, monkeypatch):
    from finance_analysis.analysis.stock_report_analyzer import StockReportAnalyzer

    call = Mock(return_value=LLMResult("report", "api"))
    monkeypatch.setattr(LLMClient, "complete_text", call)
    analyzer = StockReportAnalyzer(config=SimpleNamespace(llm=config), uid=42)
    assert analyzer.generate_text("review", max_tokens=123) == "report"
    request = call.call_args.args[0]
    assert request.uid == 42 and request.call_type == "market_review" and request.max_tokens == 123
    call.side_effect = LLMError("failed")
    assert analyzer.generate_text("review") is None

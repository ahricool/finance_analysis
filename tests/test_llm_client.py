"""Offline API/SSH boundaries, one retry budget and credential-safe auditing."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import paramiko
import pytest

from finance_analysis.llm import LLMClient, LLMError, LLMRequest, LLMResult
from finance_analysis.llm import api, remote_cli
from finance_analysis.llm.config import LLMConfig, get_llm_config


@pytest.fixture
def config(tmp_path, monkeypatch):
    from finance_analysis.database import DatabaseManager

    db = Mock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.scalar_one.return_value = True
    db.connect.return_value = connection
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: db)
    return LLMConfig(model="openai/test", api_key="private-api-secret", log_dir=tmp_path)


@pytest.mark.parametrize("backend", ["api", "cli"])
@pytest.mark.parametrize("failures", [0, 1, 2, 3, 4])
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
    if failures == 4:
        with pytest.raises(LLMError) as error:
            client.complete_text(request)
        assert "private" not in str(error.value)
    else:
        assert client.complete_text(request).text == "ok"
    assert call.call_count == min(failures + 1, 4)
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
    [{"backend": "other"}, {"cli_engine": "other"}, {"max_retries": 4}, {"timeout": 0}],
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
    assert isinstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.AutoAddPolicy)


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


@pytest.fixture
def cli_lock(config, monkeypatch):
    from finance_analysis.database import DatabaseManager
    from finance_analysis.llm import client

    config = replace(config, backend="cli", cli_ssh_username="user", cli_ssh_password="secret", max_retries=0)
    connection = DatabaseManager.get_instance().connect.return_value
    events = []
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(client.time, "monotonic", lambda: clock.now)

    def sleep(seconds):
        assert 0 < seconds <= client.CLI_LOCK_POLL_SECONDS
        clock.now += seconds

    monkeypatch.setattr(client.time, "sleep", sleep)

    def execute(statement, params):
        assert params == {"key": client.CLI_ADVISORY_LOCK_KEY}
        events.append("acquire" if "pg_try_advisory_lock" in str(statement) else "release")
        return SimpleNamespace(scalar_one=lambda: True)

    connection.execute.side_effect = execute

    def complete(config, request):
        events.append("call")
        return LLMResult("ok", "cli", engine=config.cli_engine)

    call = Mock(side_effect=complete)
    monkeypatch.setattr(remote_cli, "complete", call)
    return SimpleNamespace(config=config, connection=connection, events=events, clock=clock, call=call)


@pytest.mark.parametrize("engine", ["agy", "codex"])
def test_cli_engines_share_session_lock(cli_lock, engine):
    ctx = cli_lock
    result = LLMClient(replace(ctx.config, cli_engine=engine)).complete_text(LLMRequest("prompt"))
    assert result.engine == engine
    assert ctx.events == ["acquire", "call", "release"]
    ctx.connection.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")
    ctx.connection.__exit__.assert_called_once()
    ctx.connection.invalidate.assert_not_called()


def test_api_does_not_acquire_lock(config, monkeypatch):
    from finance_analysis.database import DatabaseManager

    monkeypatch.setattr(api, "complete", Mock(return_value=LLMResult("ok", "api")))
    LLMClient(config).complete_text(LLMRequest("prompt"))
    DatabaseManager.get_instance().connect.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError(), TimeoutError(), KeyboardInterrupt()])
def test_cli_failure_releases_lock(cli_lock, error):
    ctx = cli_lock
    ctx.call.side_effect = error
    with pytest.raises(KeyboardInterrupt if isinstance(error, KeyboardInterrupt) else LLMError):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    assert ctx.events == ["acquire", "release"]
    ctx.connection.__exit__.assert_called_once()


def test_cli_lock_wait_exhausts_total_deadline(cli_lock):
    ctx = cli_lock
    ctx.connection.execute.side_effect = None
    ctx.connection.execute.return_value.scalar_one.return_value = False
    with pytest.raises(LLMError, match="TimeoutError"):
        LLMClient(replace(ctx.config, max_retries=1)).complete_text(LLMRequest("prompt", timeout=0.25))
    assert ctx.clock.now == pytest.approx(0.25)
    ctx.call.assert_not_called()
    assert ctx.connection.execute.call_count == 1
    assert all("pg_try_advisory_lock" in str(call.args[0]) for call in ctx.connection.execute.call_args_list)
    ctx.connection.__exit__.assert_called_once()


def test_cli_wait_reduces_remaining_timeout(cli_lock):
    ctx = cli_lock
    ctx.connection.execute.side_effect = [
        SimpleNamespace(scalar_one=Mock(return_value=value)) for value in [False, False, True, True]
    ]
    request = LLMRequest("prompt", timeout=300)
    LLMClient(ctx.config).complete_text(request)
    assert ctx.call.call_args.args[1].timeout == pytest.approx(298.0)
    assert request.timeout == 300


def test_cli_acquired_at_deadline_releases_without_call(cli_lock):
    ctx = cli_lock

    def execute(statement, params):
        ctx.clock.now = 300
        ctx.events.append(str(statement))
        return SimpleNamespace(scalar_one=lambda: True)

    ctx.connection.execute.side_effect = execute
    with pytest.raises(LLMError, match="TimeoutError"):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt", timeout=300))
    ctx.call.assert_not_called()
    assert ctx.events == ["SELECT pg_try_advisory_lock(:key)", "SELECT pg_advisory_unlock(:key)"]


@pytest.mark.parametrize("validation_failure", [False, True])
def test_cli_retry_acquires_and_releases_each_attempt(cli_lock, validation_failure):
    ctx = cli_lock

    def complete(config, request):
        ctx.events.append("call")
        ctx.clock.now += 10
        if ctx.call.call_count == 1:
            if validation_failure:
                return LLMResult("invalid", "cli")
            raise RuntimeError()
        return LLMResult("{}", "cli")

    ctx.call.side_effect = complete
    LLMClient(replace(ctx.config, max_retries=1)).complete_text(
        LLMRequest("prompt", timeout=300), validator=json.loads,
    )
    assert ctx.events == ["acquire", "call", "release"] * 2
    assert [call.args[1].timeout for call in ctx.call.call_args_list] == [300, 290]
    assert ctx.connection.__exit__.call_count == 2


@pytest.mark.parametrize("failure_at", ["acquire", "release"])
def test_cli_lock_sql_failure_discards_connection(cli_lock, failure_at):
    ctx = cli_lock
    success = SimpleNamespace(scalar_one=lambda: True)
    ctx.connection.execute.side_effect = (
        [RuntimeError()] if failure_at == "acquire" else [success, RuntimeError()]
    )
    with pytest.raises(LLMError):
        LLMClient(ctx.config).complete_text(LLMRequest("prompt"))
    ctx.connection.invalidate.assert_called_once()
    ctx.connection.__exit__.assert_called_once()
    assert ctx.call.call_count == (0 if failure_at == "acquire" else 1)

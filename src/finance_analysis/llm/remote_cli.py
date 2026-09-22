"""Run an authenticated host CLI over SSH; prompt bytes only travel on stdin."""

import json
import shlex
import time
from pathlib import Path

import paramiko

from .cli_runner import RECEIPT
from .config import LLMConfig
from .failures import ProviderFailure
from .types import LLMRequest, LLMResult


def build_command(config: LLMConfig, timeout: float) -> str:
    if config.cli_engine == "agy":
        command = (
            shlex.quote(config.cli_agy_path)
            + " --input-format stream-json --output-format stream-json --sandbox --disable-slash-commands"
        )
        command += f" --print-timeout {timeout:g}s"
        if config.cli_model:
            command += " --model " + shlex.quote(config.cli_model)
        if config.cli_effort:
            command += " --effort " + shlex.quote(config.cli_effort)
    else:
        command = (
            shlex.quote(config.cli_codex_path) + " exec --json --sandbox read-only --skip-git-repo-check --ephemeral"
            " --ignore-user-config --ignore-rules -c approval_policy=never"
        )
        if config.cli_model:
            command += " --model " + shlex.quote(config.cli_model)
        if config.cli_effort:
            command += " -c " + shlex.quote("model_reasoning_effort=" + json.dumps(config.cli_effort))
        command += " -"
    return command


def supervised_command(config: LLMConfig, timeout: float) -> str:
    # Only trusted supervisor source/config go into argv. Prompt stays on stdin.
    source = Path(__file__).with_name("cli_runner.py").read_text()
    args = [
        shlex.split(build_command(config, timeout)),
        config.cli_engine,
        max(0.01, timeout - 0.5),
        config.cli_remote_workdir,
    ]
    return "exec " + shlex.join([config.cli_python_path, "-c", source, json.dumps(args)])


SAFE_CODES = {
    "quota_exhausted",
    "authentication_failed",
    "model_unavailable",
    "rate_limited",
    "service_unavailable",
    "timeout",
    "output_too_large",
    "cli_failed",
    "executable_missing",
    "interrupted",
    "supervisor_failed",
    "cleanup_failed",
}


def read_receipt(stderr: bytes):
    receipts = []
    for line in stderr.decode("utf-8", errors="replace").splitlines():
        if line.startswith(RECEIPT):
            try:
                value = json.loads(line[len(RECEIPT) :])
            except ValueError:
                continue
            if isinstance(value, dict) and value.get("code") in SAFE_CODES | {None}:
                receipts.append(value)
    if len(receipts) != 1 or receipts[0].get("cleaned") is not True:
        raise ProviderFailure("cleanup_unconfirmed", fatal=True)
    return receipts[0]


def parse_agy(stdout: str, model: str | None = None) -> LLMResult:
    payload = None
    for line in stdout.splitlines():
        event = json.loads(line)
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            raise ValueError("Malformed AGY event")
        if event["event"] == "result":
            if payload is not None:
                raise ValueError("AGY returned multiple results for one prompt")
            payload = event.get("result")
    if not isinstance(payload, dict) or payload.get("status") != "SUCCESS":
        raise ValueError("AGY returned a failed status")
    text = payload.get("response")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("AGY returned empty response")
    raw = payload.get("usage") or {}
    usage = {key: int(raw.get(key) or 0) for key in ("input_tokens", "output_tokens", "total_tokens")}
    return LLMResult(text=text, backend="cli", engine="agy", model=model, usage=usage)


def parse_codex(stdout: str, model: str | None = None) -> LLMResult:
    text = None
    usage = {}
    completed = False
    for line in stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("Malformed Codex event")
        kind = event["type"]
        if kind in {"error", "turn.failed"}:
            raise ValueError("Codex returned an error event")
        if kind == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                raise ValueError("Malformed Codex item")
            if item.get("type") == "agent_message":
                text = item.get("text")
        elif kind == "turn.completed":
            completed = True
            raw = event.get("usage") or {}
            usage = {key: int(raw.get(key) or 0) for key in ("input_tokens", "output_tokens")}
            usage["total_tokens"] = sum(usage.values())
    if not completed or not isinstance(text, str) or not text.strip():
        raise ValueError("Codex did not complete with a final message")
    return LLMResult(text=text, backend="cli", engine="codex", model=model, usage=usage)


def complete(config: LLMConfig, request: LLMRequest) -> LLMResult:
    timeout = request.timeout or config.timeout
    deadline = time.monotonic() + timeout
    prompt = request.prompt
    if request.system_prompt:
        prompt = request.system_prompt + "\n\n---\n\n" + prompt
    client = paramiko.SSHClient()
    channel = None
    launched = False
    try:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=config.cli_ssh_host,
            port=config.cli_ssh_port,
            username=config.cli_ssh_username,
            password=config.cli_ssh_password,
            timeout=min(timeout, 15),
            auth_timeout=min(timeout, 15),
            banner_timeout=min(timeout, 15),
            look_for_keys=False,
            allow_agent=False,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("SSH connection deadline exceeded")
        channel = client.get_transport().open_session(timeout=remaining)
        channel.settimeout(remaining)
        launched = True
        channel.exec_command(supervised_command(config, remaining))
        # Interleave writes and both output streams to avoid SSH window deadlocks.
        if config.cli_engine == "agy":
            prompt = (
                json.dumps(
                    {"event": "user", "message": {"content": prompt}},
                    ensure_ascii=False,
                )
                + "\n"
            )
        data = prompt.encode("utf-8")
        offset = 0
        eof = False
        output = bytearray()
        diagnostics = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise ProviderFailure("cleanup_unconfirmed", fatal=True)
            channel.settimeout(max(0.001, deadline - time.monotonic()))
            if offset < len(data) and channel.send_ready():
                sent = channel.send(data[offset : offset + 32768])
                if sent == 0:
                    raise ConnectionError("SSH stdin closed before prompt was sent")
                offset += sent
            if offset == len(data) and not eof:
                channel.shutdown_write()
                eof = True
            if channel.recv_ready():
                output.extend(channel.recv(65536))
            if channel.recv_stderr_ready():
                diagnostics.extend(channel.recv_stderr(65536))
                diagnostics = diagnostics[-65536:]  # Bounded; only allowlisted receipt is consumed.
            if len(output) > 16 * 1024 * 1024:
                raise ValueError("Remote CLI output exceeds 16 MiB")
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                break
            time.sleep(0.01)
        status = channel.recv_exit_status()
        receipt = read_receipt(bytes(diagnostics))
        if receipt["code"]:
            code = receipt["code"]
            raise ProviderFailure(
                code,
                retryable=code in {"rate_limited", "service_unavailable", "cli_failed"},
                fatal=code in {"cleanup_failed", "supervisor_failed", "interrupted"},
            )
        if status != 0:
            raise ProviderFailure("cli_failed", retryable=True)
        if not output.strip():
            raise ProviderFailure("empty_response", retryable=True)
        parser = parse_agy if config.cli_engine == "agy" else parse_codex
        try:
            return parser(output.decode("utf-8"), config.cli_model or receipt.get("model") or None)
        except (ValueError, TypeError, KeyError):
            raise ProviderFailure("invalid_output", retryable=True) from None
    except ProviderFailure:
        raise
    except Exception as exc:
        if launched:
            raise ProviderFailure("cleanup_unconfirmed", fatal=True) from None
        raise exc
    finally:
        if channel is not None:
            channel.close()
        client.close()

"""Run an authenticated host CLI over SSH; prompt bytes only travel on stdin."""

import json
import shlex
import time

import paramiko

from .config import LLMConfig
from .types import LLMRequest, LLMResult


def build_command(config: LLMConfig, timeout: float) -> str:
    if config.cli_engine == "agy":
        command = (
            "/usr/local/bin/agy --input-format stream-json --output-format stream-json --sandbox --disable-slash-commands"
        )
        command += f" --print-timeout {timeout:g}s"
        if config.cli_model:
            command += " --model " + shlex.quote(config.cli_model)
        if config.cli_effort:
            command += " --effort " + shlex.quote(config.cli_effort)
    else:
        command = (
            "/usr/local/bin/codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral"
            " --ignore-user-config --ignore-rules -c approval_policy=never"
        )
        if config.cli_model:
            command += " --model " + shlex.quote(config.cli_model)
        if config.cli_effort:
            command += " -c " + shlex.quote("model_reasoning_effort=" + json.dumps(config.cli_effort))
        command += " -"
    workdir = shlex.quote(config.cli_remote_workdir)
    return f"umask 077; mkdir -p {workdir} && cd {workdir} && exec {command}"


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
        channel.exec_command(build_command(config, remaining))
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
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Remote CLI command timed out")
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
                channel.recv_stderr(65536)  # Drain; never propagate credential-bearing CLI diagnostics.
            if len(output) > 16 * 1024 * 1024:
                raise ValueError("Remote CLI output exceeds 16 MiB")
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                break
            time.sleep(0.01)
        status = channel.recv_exit_status()
        if status != 0:
            raise RuntimeError(f"Remote CLI exited with status {status}")
        if not output.strip():
            raise ValueError("Remote CLI stdout is empty")
        parser = parse_agy if config.cli_engine == "agy" else parse_codex
        return parser(output.decode("utf-8"), config.cli_model or None)
    finally:
        if channel is not None:
            channel.close()
        client.close()

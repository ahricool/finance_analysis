"""Stdlib-only SSH supervisor, shipped as python -c source; no host installation.

The CLI inherits SSH stdin. Only CLI stdout and an allowlisted completion
receipt leave the host. Private AGY diagnostics are scoped to this invocation.
"""

import json
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time

RECEIPT = "FA_LLM_RECEIPT "
MAX_BYTES = 16 * 1024 * 1024


class RunnerInterrupted(Exception):
    """Unlike InterruptedError, selectors must not swallow this signal."""


def diagnostic_code(message):
    """Called only for diagnostics/error events, never assistant response text."""
    text = message.lower()
    if any(
        s in text
        for s in (
            "individual quota reached",
            "insufficient_quota",
            "exceeded your current quota",
            "you've hit your usage limit",
            "usage limit reached",
        )
    ):
        return "quota_exhausted"
    if any(s in text for s in ("authentication required", "invalid api key", "unauthorized", "please log in")):
        return "authentication_failed"
    if any(s in text for s in ("invalid model selection", "model_not_found", "model does not exist")):
        return "model_unavailable"
    if any(s in text for s in ("code 429", "rate_limit_exceeded", "too many requests")):
        return "rate_limited"
    if any(
        s in text
        for s in (
            "code 500",
            "code 502",
            "code 503",
            "code 504",
            "connection reset",
            "connection refused",
            "temporarily unavailable",
        )
    ):
        return "service_unavailable"
    return None


def stop_group(process, deadline):
    """Kill only this request's process group, including surviving descendants."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
            return True
        except PermissionError:
            # macOS can report EPERM for a just-exited zombie group. Reap and
            # recheck below; a genuine permission failure remains unconfirmed.
            pass
        until = min(deadline, time.monotonic() + (0.3 if sig == signal.SIGTERM else 1.0))
        while time.monotonic() < until:
            process.poll()  # Reap the group leader before testing group existence.
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                pass
            time.sleep(0.02)
    return False


def supervise(argv, engine, timeout, workdir):
    started = time.monotonic()
    deadline = started + timeout
    run_deadline = deadline - min(2.0, timeout / 3)
    process = None
    code = None
    model = None
    cleaned = True
    log_offset = 0
    log_tail = ""
    streams = {"out": b"", "err": b""}
    total_output = 0
    with tempfile.TemporaryDirectory(prefix=".llm-", dir=workdir) as tmp:
        log_path = os.path.join(tmp, "agy.log")
        if engine == "agy":
            argv = argv + ["--log-file", log_path]
        try:
            process = subprocess.Popen(
                argv,
                stdin=sys.stdin.buffer,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                cwd=workdir,
            )
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "out")
                selector.register(process.stderr, selectors.EVENT_READ, "err")
                while selector.get_map():
                    if time.monotonic() >= run_deadline:
                        code = "timeout"
                        break
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        name = key.data
                        total_output += len(chunk)
                        if total_output > MAX_BYTES:
                            code = "output_too_large"
                            break
                        if name == "out":
                            sys.stdout.buffer.write(chunk)
                            sys.stdout.buffer.flush()
                        streams[name] += chunk
                        while b"\n" in streams[name]:
                            line, streams[name] = streams[name].split(b"\n", 1)
                            message = line.decode("utf-8", errors="replace")
                            if name == "err":
                                code = diagnostic_code(message) or code
                            else:
                                try:
                                    event = json.loads(message)
                                except ValueError:
                                    continue
                                if not isinstance(event, dict):
                                    continue
                                failure = None
                                if event.get("type") in {"error", "turn.failed"}:
                                    failure = event.get("error") or event.get("message")
                                if event.get("event") == "result":
                                    result = event.get("result") or {}
                                    if isinstance(result, dict) and result.get("status") != "SUCCESS":
                                        failure = result.get("error")
                                if failure:
                                    code = diagnostic_code(json.dumps(failure)) or code
                        streams[name] = streams[name][-65536:]
                    # AGY emits its retry reason only in the native log. Ignore
                    # startup auth/cache warnings, also present in successful runs.
                    if engine == "agy" and os.path.exists(log_path):
                        with open(log_path, "rb") as handle:
                            handle.seek(log_offset)
                            chunk = handle.read(262144)
                            log_offset = handle.tell()
                        log_tail += chunk.decode("utf-8", errors="replace")
                        lines = log_tail.split("\n")
                        log_tail = lines.pop()[-65536:]
                        for line in lines:
                            if "run.go:" in line and "Run: attempt" in line and "failed (" in line:
                                code = diagnostic_code(line) or code
                            if "model_config_manager.go:" in line:
                                match = re.search(r'label="([A-Za-z0-9 ._()/+-]{1,160})"', line)
                                if match:
                                    model = match[1]
                    if code:
                        break
                if not code:
                    remaining = run_deadline - time.monotonic()
                    status = process.wait(timeout=max(0.01, remaining))
                    for tail in (streams["err"],):
                        code = diagnostic_code(tail.decode("utf-8", errors="replace")) or code
                    if status and not code:
                        code = "cli_failed"
        except FileNotFoundError:
            code = "executable_missing"
        except subprocess.TimeoutExpired:
            code = "timeout"
        except (KeyboardInterrupt, RunnerInterrupted, BrokenPipeError):
            code = "interrupted"
        except Exception:
            code = "supervisor_failed"
        finally:
            if process is not None:
                try:
                    cleaned = stop_group(process, deadline)
                except Exception:
                    cleaned = False
                process.stdout.close()
                process.stderr.close()
    if not cleaned:
        code = "cleanup_failed"
    receipt = dict(code=code, cleaned=cleaned, model=model)
    sys.stderr.write(RECEIPT + json.dumps(receipt) + "\n")
    sys.stderr.flush()
    return 1 if code else 0


def main():
    def interrupted(*_):
        raise RunnerInterrupted()

    signal.signal(signal.SIGHUP, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    argv, engine, timeout, workdir = json.loads(sys.argv[1])
    os.umask(0o077)
    os.makedirs(workdir, mode=0o700, exist_ok=True)
    return supervise(argv, engine, timeout, workdir)


if __name__ == "__main__":
    sys.exit(main())

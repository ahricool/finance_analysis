"""Real local child processes exercise the SSH supervisor without LLM/network."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from finance_analysis.llm import cli_runner, remote_cli
from finance_analysis.llm.failures import ProviderFailure


def run(tmp_path, code, *, engine="codex", timeout=4):
    child = tmp_path / "fake_cli.py"
    child.write_text(code)
    argv = [[sys.executable, str(child)], engine, timeout, str(tmp_path)]
    result = subprocess.run(
        [sys.executable, "-c", Path(cli_runner.__file__).read_text(), json.dumps(argv)],
        input="中文 prompt",
        capture_output=True,
        text=True,
        timeout=timeout + 4,
    )
    return result, remote_cli.read_receipt(result.stderr.encode())


def test_runner_forwards_stdin_stdout_and_removes_private_logs(tmp_path):
    result, receipt = run(
        tmp_path,
        """import json,sys
print(json.dumps({"type":"item.completed", "item":{"type":"agent_message","text":sys.stdin.read()}}))
print(json.dumps({"type":"turn.completed"}))
print("secret credentials never forwarded",file=sys.stderr)
""",
    )
    assert result.returncode == 0
    assert remote_cli.parse_codex(result.stdout).text == "中文 prompt"
    assert receipt == dict(code=None, cleaned=True, model=None)
    assert "secret credentials" not in result.stderr
    assert not list(tmp_path.glob(".llm-*"))


def test_agy_quota_in_private_log_fails_fast(tmp_path):
    started = time.monotonic()
    result, receipt = run(
        tmp_path,
        """import sys,time
from pathlib import Path
p=Path(sys.argv[sys.argv.index('--log-file')+1])
p.write_text('W cache.go:135] You are not logged into Antigravity.\\n'
             'I model_config_manager.go:327] label="Gemini Test (High)"\\n'
             'I run.go:389] Run: attempt 1 failed (RESOURCE_EXHAUSTED (code 429): Individual quota reached. private-secret), retrying in 4s\\n')
time.sleep(60)
""",
        engine="agy",
        timeout=8,
    )
    assert time.monotonic() - started < 4
    assert receipt == dict(code="quota_exhausted", cleaned=True, model="Gemini Test (High)")
    assert "private-secret" not in result.stdout + result.stderr
    assert not list(tmp_path.glob(".llm-*"))


def test_startup_auth_warning_does_not_fail_successful_agy(tmp_path):
    result, receipt = run(
        tmp_path,
        """import sys,json,time
from pathlib import Path
Path(sys.argv[sys.argv.index('--log-file')+1]).write_text('W cache.go:135] error getting token: You are not logged into Antigravity.\\n')
time.sleep(.1)
print(json.dumps({'event':'result','result':{'status':'SUCCESS','response':'quota_exhausted is only answer text'}}))
""",
        engine="agy",
    )
    assert result.returncode == 0 and receipt["code"] is None


def test_timeout_kills_child_and_does_not_touch_unrelated_process(tmp_path):
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    try:
        result, receipt = run(
            tmp_path,
            """import os,signal,time
from pathlib import Path
Path('child.pid').write_text(str(os.getpid()))
signal.signal(signal.SIGTERM,signal.SIG_IGN)
time.sleep(60)
""",
            timeout=2,
        )
        pid = int((tmp_path / "child.pid").read_text())
        assert receipt["code"] == "timeout" and receipt["cleaned"]
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=3)


def test_cleanup_covers_spawned_process_group(tmp_path):
    result, receipt = run(
        tmp_path,
        """import subprocess,sys,time,signal
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
Path('descendant.pid').write_text(str(child.pid))
def stop(*_):
    child.wait(timeout=1)
    sys.exit(0)
signal.signal(signal.SIGTERM,stop)
time.sleep(60)
""",
        timeout=3,
    )
    assert receipt["cleaned"]
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "descendant.pid").read_text()), 0)


def test_missing_executable_returns_safe_receipt(tmp_path):
    args = [[str(tmp_path / "missing-cli")], "codex", 3, str(tmp_path)]
    result = subprocess.run(
        [sys.executable, "-c", Path(cli_runner.__file__).read_text(), json.dumps(args)],
        input="prompt",
        capture_output=True,
        text=True,
        timeout=6,
    )
    assert remote_cli.read_receipt(result.stderr.encode())["code"] == "executable_missing"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"private diagnostics",
        b'FA_LLM_RECEIPT {"cleaned":false,"code":null}',
        b'FA_LLM_RECEIPT {"cleaned":true,"code":"private-secret"}',
    ],
)
def test_no_switch_without_confirmed_cleanup(raw):
    with pytest.raises(ProviderFailure, match="cleanup_unconfirmed") as exc:
        remote_cli.read_receipt(raw)
    assert exc.value.fatal


def test_ssh_disconnect_signal_reaps_child(tmp_path):
    child = tmp_path / "fake.py"
    child.write_text(
        "import os,time\nfrom pathlib import Path\nPath('pid').write_text(str(os.getpid()))\ntime.sleep(60)"
    )
    args = [[sys.executable, str(child)], "codex", 8, str(tmp_path)]
    proc = subprocess.Popen(
        [sys.executable, "-c", Path(cli_runner.__file__).read_text(), json.dumps(args)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 3
        while not (tmp_path / "pid").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (tmp_path / "pid").exists()
        proc.send_signal(signal.SIGHUP)
        _, stderr = proc.communicate(timeout=3)
        assert remote_cli.read_receipt(stderr)["cleaned"]
        with pytest.raises(ProcessLookupError):
            os.kill(int((tmp_path / "pid").read_text()), 0)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()

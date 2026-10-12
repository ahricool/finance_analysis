"""Exercise the deployment entry point against isolated Git/Docker processes."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "deploy.py"))
Deployment = DEPLOY["Deployment"]
DeployError = DEPLOY["DeployError"]
REVISION = "a" * 40
SERVICES = DEPLOY["APP_SERVICES"]

FAKE_CLI = r'''import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
path = Path(os.environ["FAKE_DEPLOY_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
tool = Path(sys.argv[0]).name
state["calls"].append([tool, *args])
def save(): path.write_text(json.dumps(state))
def finish(value="", code=0):
    save()
    if value: print(value)
    sys.exit(code)
if tool == "git":
    if args == ["rev-parse", "--git-path", "finance-deploy"]: finish(".git/finance-deploy")
    if args == ["rev-parse", "HEAD"]: finish(state["revision"])
    if args[0] == "status": finish(" M dirty" if state.get("dirty") else "")
    finish()
if args[0] == "compose":
    args = args[1:]
    while args and args[0] == "-f": args = args[2:]
    command = args[0]
    if command == "config":
        tag = os.environ.get("IMAGE_TAG", "latest")
        finish(json.dumps({"services": {
            service: {"image": f"ghcr.io/test/{service}:{tag}"}
            for service in state["services"] if service not in ("postgres", "redis")
        }}))
    if command == "ps":
        service = args[-1]
        finish(state["services"].get(service, ""))
    if command == "pull": finish(code=1 if state.get("fail_pull") else 0)
    if command == "stop":
        for service in args[1:]:
            key = state["services"].get(service)
            if key: state["containers"][key]["state"]["Running"] = False
        finish()
    if command == "run": finish(code=1 if state.get("fail_migration") else 0)
    if command == "up":
        services = [arg for arg in args if arg in state["services"]]
        for service in services:
            key = "new-" + service
            state["services"][service] = key
            state["containers"][key] = {
                "id": key, "image": "sha256:new-" + service,
                "state": {"Running": True, "ExitCode": 0, "OOMKilled": False,
                          "StartedAt": datetime.now(timezone.utc).isoformat(),
                          "Health": {"Status": "healthy"}},
                "command": ["celery"], "stop_signal": "",
            }
        finish(code=1 if state.get("fail_up") in services else 0)
    if command == "exec":
        finish(state.get("heartbeat", "2999-01-01T00:00:00+00:00"))
    finish()
if args[0:2] == ["image", "inspect"]:
    service = args[-1].split("/")[-1].split(":")[0]
    finish(json.dumps({
        "id": "sha256:new-" + service,
        "revision": "wrong" if state.get("bad_revision") == service else state["revision"],
        "digests": [f"ghcr.io/test/{service}@sha256:new-{service}"],
    }))
if args[0] == "inspect": finish(json.dumps(state["containers"][args[-1]]))
if args[0] == "exec":
    if "REMAP_SIGTERM" in args[-1]: finish("True" if state.get("remap_sigterm") else "False")
    finish()
if args[0] == "start":
    if state.get("fail_start") == args[-1]: finish(code=1)
    state["containers"][args[-1]]["state"]["Running"] = True
    finish()
if args[0] == "stop":
    save()
    time.sleep(state.get("stop_delay", 0))
    state = json.loads(path.read_text())
    for key in args[3:]:
        container_state = state["containers"][key]["state"]
        container_state["Running"] = False
        container_state["ExitCode"] = state.get("stop_exit_code", 0)
    finish(code=1 if state.get("fail_stop") else 0)
finish(code=2)
'''


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    state = {"revision": REVISION, "calls": [], "services": {}, "containers": {}}
    for service in (*SERVICES, "postgres", "redis"):
        key = "old-" + service
        state["services"][service] = key
        state["containers"][key] = {
            "id": key, "image": "sha256:old-" + service,
            "state": {"Running": True, "ExitCode": 0, "OOMKilled": False, "Health": {"Status": "healthy"}},
            "command": ["celery", "beat"] if service == "beat" else ["celery"], "stop_signal": "",
        }
    state_path = tmp_path / "fake-state.json"
    state_path.write_text(json.dumps(state))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("git", "docker"):
        executable = bin_dir / name
        executable.write_text(f"#!{sys.executable}\n" + FAKE_CLI)
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DEPLOY_STATE", str(state_path))
    monkeypatch.setenv("DEPLOY_READY_TIMEOUT", "1")
    original_sleep = DEPLOY["time"].sleep
    monkeypatch.setattr(DEPLOY["time"], "sleep", lambda seconds: original_sleep(min(seconds, 0.01)))
    instance = Deployment(tmp_path)

    def update(**changes):
        state = json.loads(state_path.read_text())
        state.update(changes)
        state_path.write_text(json.dumps(state))

    return instance, state_path, update


def read_state(path):
    return json.loads(path.read_text())


def command_index(calls, prefix):
    return next(index for index, call in enumerate(calls) if call[:len(prefix)] == prefix)


def test_docker_nanosecond_timestamp_is_normalized_for_host_python():
    value = DEPLOY["parse_timestamp"]("2026-10-12T11:00:00.123456789Z")
    assert value.isoformat() == "2026-10-12T11:00:00.123456+00:00"


def test_deploy_prepares_before_pause_and_never_replaces_infrastructure(deployment):
    instance, path, _ = deployment
    instance.execute([])
    state = read_state(path)
    calls = state["calls"]
    pull = next(i for i, call in enumerate(calls) if "pull" in call and "compose" in call)
    beat_stop = command_index(calls, ["docker", "stop", "--timeout", "-1", "old-beat"])
    workers_stop = command_index(calls, ["docker", "stop", "--timeout", "-1", "old-worker", "old-qlib-worker"])
    migration = next(i for i, call in enumerate(calls) if "run" in call and "compose" in call)
    ups = [(i, call) for i, call in enumerate(calls) if "up" in call and "compose" in call]
    assert pull < beat_stop < workers_stop < migration < ups[0][0]
    assert ups[-1][1][-1] == "beat"
    assert "--force-recreate" in ups[-1][1]
    assert all("--force-recreate" not in call for _, call in ups[:-1])
    for _, call in ups:
        assert "--no-deps" in call and "--no-build" in call and "never" in call and "--wait" in call
        assert "postgres" not in call and "redis" not in call and "--remove-orphans" not in call
    assert state["services"]["redis"] == "old-redis"
    assert state["containers"]["old-redis"]["state"]["Running"]
    assert not instance.pending_path.exists()
    assert read_state(instance.release_path)["tag"] == f"sha-{REVISION}"
    assert all("@sha256:" in image["image"] for image in read_state(instance.override_path)["services"].values())


@pytest.mark.parametrize("failure", [
    {"fail_pull": True}, {"bad_revision": "web"}, {"dirty": True}, {"remap_sigterm": True},
])
def test_preflight_failure_leaves_all_running_tasks_untouched(deployment, failure):
    instance, path, update = deployment
    update(**failure)
    with pytest.raises((DeployError, subprocess.CalledProcessError)):
        instance.execute([])
    state = read_state(path)
    assert all(container["state"]["Running"] for container in state["containers"].values())
    assert not instance.pending_path.exists()


def test_legacy_worker_without_explicit_stop_signal_uses_sigterm(deployment):
    instance, path, update = deployment
    state = read_state(path)
    state["containers"]["old-worker"]["stop_signal"] = None
    update(containers=state["containers"])
    instance.execute([])
    assert not instance.pending_path.exists()


def test_already_stopped_beat_still_allows_workers_to_drain(deployment):
    instance, path, update = deployment
    state = read_state(path)
    state["containers"]["old-beat"]["state"]["Running"] = False
    update(containers=state["containers"])
    instance.execute([])
    assert not instance.pending_path.exists()
    assert read_state(path)["containers"]["old-worker"]["state"]["Running"] is False


def test_bash_entrypoint_runs_complete_deployment_with_stdlib_host_python(deployment):
    instance, _, _ = deployment
    project = Path(__file__).resolve().parents[1]
    scripts = instance.root / "scripts"
    scripts.mkdir()
    (scripts / "deploy.py").write_text((project / "scripts" / "deploy.py").read_text())
    (instance.root / "deploy.sh").write_text((project / "deploy.sh").read_text())
    result = subprocess.run(
        ["bash", "deploy.sh"], cwd=instance.root, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "生产环境部署完成" in result.stdout
    assert read_state(instance.release_path)["phase"] == "complete"


def test_failed_drain_cannot_be_mistaken_for_success_or_automatically_start_beat(deployment):
    instance, path, update = deployment
    update(stop_exit_code=137)
    with pytest.raises(DeployError, match="未正常退出"):
        instance.execute([])
    assert instance.pending_path.exists() and not instance.release_path.exists()
    calls = read_state(path)["calls"]
    assert not any("up" in call or call[:2] == ["docker", "start"] for call in calls)
    with pytest.raises(DeployError, match="尚未正常停止"):
        instance.execute(["--recover"])


def test_recovery_uses_original_container_ids_without_recreation(deployment):
    instance, path, _ = deployment
    instance.prepare()
    instance.drain()
    instance.execute(["--recover"])
    calls = read_state(path)["calls"]
    starts = [call[-1] for call in calls if call[:2] == ["docker", "start"]]
    assert starts == ["old-worker", "old-qlib-worker", "old-beat"]
    assert not any("up" in call for call in calls)
    assert not instance.pending_path.exists()


def test_recovery_after_beat_only_stop_keeps_running_workers(deployment):
    instance, path, _ = deployment
    instance.prepare()
    instance.pending["paused_at"] = DEPLOY["utc_now"]()
    instance.phase("pausing")
    instance.stop(["old-beat"])
    instance.execute(["--recover"])
    starts = [call[-1] for call in read_state(path)["calls"] if call[:2] == ["docker", "start"]]
    assert starts == ["old-beat"]


def test_interruption_keeps_journal_and_requires_inflight_stop_to_finish(deployment, monkeypatch):
    instance, path, update = deployment
    update(stop_delay=1)

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(DEPLOY["time"], "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        instance.execute([])
    assert read_state(instance.pending_path)["stop_requested_ids"] == ["old-beat"]
    with pytest.raises(DeployError, match="尚未正常停止"):
        instance.execute(["--recover"])
    assert not any("up" in call for call in read_state(path)["calls"])


def test_partially_failed_recovery_can_be_retried_without_restarting_running_worker(deployment):
    instance, path, update = deployment
    instance.prepare()
    instance.drain()
    update(fail_start="old-qlib-worker")
    with pytest.raises(subprocess.CalledProcessError):
        instance.execute(["--recover"])
    update(fail_start=None)
    instance.execute(["--recover"])
    worker_starts = [
        call for call in read_state(path)["calls"] if call[:2] == ["docker", "start"] and call[-1] == "old-worker"
    ]
    assert len(worker_starts) == 1
    assert not instance.pending_path.exists()


def test_partial_replacement_requires_resume_and_does_not_roll_back_migrations(deployment):
    instance, path, update = deployment
    update(fail_migration=True)
    with pytest.raises(subprocess.CalledProcessError):
        instance.execute([])
    with pytest.raises(DeployError, match="禁止自动回滚"):
        instance.execute(["--recover"])
    update(fail_migration=False)
    instance.execute(["--resume"])
    assert not instance.pending_path.exists()
    assert read_state(path)["services"]["beat"] == "new-beat"


def test_resume_interrupted_during_drain_keeps_migration_boundary(deployment):
    instance, _, update = deployment
    update(fail_up="web")
    with pytest.raises(subprocess.CalledProcessError):
        instance.execute([])
    update(fail_stop=True)
    with pytest.raises(DeployError, match="优雅停止失败"):
        instance.execute(["--resume"])
    with pytest.raises(DeployError, match="禁止自动回滚"):
        instance.execute(["--recover"])


def test_beat_startup_failure_stops_the_new_scheduler(deployment):
    instance, path, update = deployment
    update(fail_up="beat")
    with pytest.raises(subprocess.CalledProcessError):
        instance.execute([])
    assert not read_state(path)["containers"]["new-beat"]["state"]["Running"]
    assert not instance.release_path.exists()


def test_old_heartbeat_does_not_prove_new_scheduler_ready(deployment):
    instance, path, update = deployment
    update(heartbeat="2000-01-01T00:00:00+00:00")
    with pytest.raises(DeployError, match="新的心跳"):
        instance.execute([])
    assert not read_state(path)["containers"]["new-beat"]["state"]["Running"]


def test_pending_journal_blocks_another_deploy_or_mutating_passthrough(deployment):
    instance, _, update = deployment
    update(fail_migration=True)
    with pytest.raises(subprocess.CalledProcessError):
        instance.execute([])
    for args in ([], ["up", "-d"], ["restart", "worker"]):
        with pytest.raises(DeployError, match="未完成部署"):
            instance.execute(args)
    instance.execute(["ps"])
    instance.execute(["--status"])


def test_lock_is_exclusive_and_status_remains_available(deployment):
    instance, _, _ = deployment
    with instance.lock():
        with pytest.raises(DeployError, match="已有部署"):
            instance.execute([])
        instance.execute(["--status"])
        instance.execute(["ps"])
        instance.execute(["logs", "--tail", "10", "worker"])


def test_maintenance_commands_use_successful_release_digests(deployment):
    instance, path, _ = deployment
    instance.execute([])
    instance.execute(["start", "web"])
    call = read_state(path)["calls"][-1]
    assert str(instance.override_path) in call
    assert call[-2:] == ["start", "web"]

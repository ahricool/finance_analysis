"""Deployment orchestration tests; no Docker, Git, database or network calls."""

import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location("deploy_script", Path(__file__).parents[1] / "scripts/deploy.py")
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


@pytest.fixture
def deployment(tmp_path):
    instance = deploy.Deployment.__new__(deploy.Deployment)
    instance.root = instance.directory = tmp_path
    instance.pending_path = tmp_path / "pending.json"
    instance.release_path = tmp_path / "release.json"
    instance.override_path = tmp_path / "target-compose.json"
    instance.pending = {}
    instance.env = {}
    instance.warn_after = 900
    instance.wait_timeout = 300
    instance.lock = nullcontext
    instance.log = Mock()
    instance.compose = Mock()
    instance.run = Mock()
    return instance


@pytest.mark.parametrize("args", [[], ["--resume"]])
@pytest.mark.parametrize("phase", ["draining", "replacing", "starting_beat"])
def test_retry_prepares_new_release_despite_old_pending(deployment, args, phase):
    old = {"revision": "old-sha", "phase": phase, "replacement_started_at": "old-time"}
    deployment.pending_path.write_text(json.dumps(old))
    calls = []

    def prepare():
        calls.append("prepare-latest-main")
        deployment.pending = {"revision": "new-sha"}

    deployment.prepare = prepare
    deployment.drain = lambda: calls.append("drain-current-containers")
    deployment.replace = lambda: calls.append("migrate-and-replace")
    deployment.execute(args)
    assert calls == ["prepare-latest-main", "drain-current-containers", "migrate-and-replace"]
    assert deployment.pending["revision"] == "new-sha"
    deployment.run.assert_not_called()  # No old HEAD comparison.


def test_failed_preparation_preserves_previous_diagnostics_and_services(deployment):
    old = '{"revision": "old-sha", "phase": "replacing"}'
    deployment.pending_path.write_text(old)
    deployment.prepare = Mock(side_effect=deploy.DeployError("image unavailable"))
    deployment.drain = Mock()
    deployment.replace = Mock()
    with pytest.raises(deploy.DeployError, match="image unavailable"):
        deployment.execute([])
    assert deployment.pending_path.read_text() == old
    deployment.drain.assert_not_called()
    deployment.replace.assert_not_called()
    deployment.compose.assert_not_called()


def test_drain_checks_stopped_workers_and_stops_beat_first(deployment):
    deployment.containers = Mock(return_value={
        "beat": {"id": "beat", "state": {"Running": True}},
        "worker": {"id": "worker", "state": {"Running": False}},
        "qlib-worker": {"id": "qlib", "state": {"Running": True}},
    })
    calls = []
    deployment.stop = lambda ids: calls.append(ids)
    deployment.drain()
    assert calls == [["beat"], ["worker", "qlib"]]
    assert deployment.pending["phase"] == "drained"


@pytest.mark.parametrize("state", [
    {"Running": True, "ExitCode": 0},
    {"Running": False, "ExitCode": 137},
    {"Running": False, "ExitCode": 0, "OOMKilled": True},
])
def test_abnormal_worker_exit_blocks_replacement(deployment, monkeypatch, state):
    process = Mock(returncode=0)
    process.poll.return_value = 0
    monkeypatch.setattr(deploy.subprocess, "Popen", Mock(return_value=process))
    deployment.inspect = Mock(return_value={"state": state})
    with pytest.raises(deploy.DeployError, match="未正常退出"):
        deployment.stop(["worker"])


def test_stop_waits_without_kill_deadline(deployment, monkeypatch):
    process = Mock(returncode=0)
    process.poll.side_effect = [None, 0, 0]
    popen = Mock(return_value=process)
    monkeypatch.setattr(deploy.subprocess, "Popen", popen)
    monkeypatch.setattr(deploy.time, "monotonic", Mock(side_effect=[0, 901]))
    monkeypatch.setattr(deploy.time, "sleep", Mock())
    deployment.inspect = Mock(return_value={"state": {"Running": False, "ExitCode": 0}})
    deployment.stop(["worker", "qlib"])
    assert popen.call_args.args[0] == ["docker", "stop", "--timeout", "-1", "worker", "qlib"]
    deployment.log.assert_called_once()
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


@pytest.mark.parametrize("beat_started", [False, True])
def test_failed_deployment_does_not_restore_old_services(deployment, beat_started):
    deployment.prepare = Mock()
    deployment.drain = Mock()

    def replace():
        deployment.phase("starting_beat" if beat_started else "replacing")
        if beat_started:
            deployment.pending["beat_starting_at"] = "now"
        raise deploy.DeployError("failed")

    deployment.replace = replace
    with pytest.raises(deploy.DeployError, match="failed"):
        deployment.execute([])
    assert deployment.pending_path.exists()
    if beat_started:
        deployment.compose.assert_called_once_with("stop", "beat")
    else:
        deployment.compose.assert_not_called()
    deployment.run.assert_not_called()


def test_replace_starts_beat_only_after_apps_are_verified(deployment):
    deployment.containers = Mock(return_value={"beat": {"state": {"StartedAt": "now"}}})
    calls = []
    deployment.compose = lambda *args, **kwargs: calls.append(args[0])
    deployment.up = lambda services, **kwargs: calls.append(services)
    deployment.verify_apps = lambda services: calls.append(("verify", services))
    deployment.verify_beat = lambda: calls.append("heartbeat")
    deployment.replace()
    assert calls == [
        "stop", "run", ("server",), ("worker", "qlib-worker", "streamer", "web"),
        ("verify", deploy.APP_SERVICES[:-1]), ("beat",), "heartbeat", ("verify", deploy.APP_SERVICES),
    ]
    assert not deployment.pending_path.exists()
    assert json.loads(deployment.release_path.read_text())["phase"] == "complete"


def test_explicit_maintenance_uses_pending_target_instead_of_old_success(deployment):
    target = {"tag": "sha-new", "images": {"server": {"image": "repo@sha256:new"}}}
    deployment.pending_path.write_text(json.dumps(target))
    deployment.release_path.write_text(json.dumps({"tag": "sha-old", "images": {}}))
    deployment.execute(["up", "-d", "server"])
    deployment.compose.assert_called_once_with("up", "-d", "server", target=True)
    assert json.loads(deployment.override_path.read_text())["services"] == target["images"]


def test_recover_explains_forward_deployment_without_starting_old_containers(deployment):
    with pytest.raises(deploy.DeployError, match="部署最新 main"):
        deployment.execute(["--recover"])
    deployment.compose.assert_not_called()
    deployment.run.assert_not_called()


def test_prepare_pulls_main_and_pins_only_this_attempt(deployment):
    def run(*args, **kwargs):
        if args == ("git", "status", "--porcelain"):
            return ""
        if args == ("git", "rev-parse", "HEAD"):
            return "new-sha"
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps({"id": "image-id", "revision": "new-sha", "digests": ["repo@sha256:new"]})
        return ""

    deployment.run = Mock(side_effect=run)
    deployment.compose.return_value = json.dumps({
        "services": {name: {"image": "repo:sha-new-sha"} for name in deploy.APP_SERVICES},
    })
    deployment.check_infrastructure = Mock()
    deployment.containers = Mock(return_value={})
    deployment.prepare()
    assert ("git", "pull", "--ff-only", "origin", "main") in [c.args for c in deployment.run.call_args_list]
    deployment.compose.assert_any_call("pull", *deploy.APP_SERVICES)
    assert deployment.pending["revision"] == "new-sha"
    assert deployment.pending["images"]["server"]["image"] == "repo@sha256:new"
    assert "old" not in deployment.pending


def test_drain_failure_never_reaches_migration(deployment):
    deployment.prepare = Mock()
    deployment.drain = Mock(side_effect=deploy.DeployError("worker still running"))
    deployment.replace = Mock()
    with pytest.raises(deploy.DeployError, match="worker still running"):
        deployment.execute([])
    deployment.replace.assert_not_called()


def test_interrupt_only_disconnects_docker_stop_client(deployment, monkeypatch):
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(deploy.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(deploy.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        deployment.stop(["worker"])
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=10)
    process.kill.assert_not_called()
    deployment.compose.assert_not_called()

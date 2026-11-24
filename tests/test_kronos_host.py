"""Exercise LaunchAgent transitions without starting host services or loading a model."""

import errno
import importlib.util
import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

SPEC = importlib.util.spec_from_file_location("kronos_host", Path(__file__).parents[1] / "scripts/kronos_host.py")
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)

DOMAIN = "gui/501"
TARGET = f"{DOMAIN}/{host.LABEL}"


@pytest.fixture
def launch_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(host.os, "getuid", lambda: 501)
    monkeypatch.setattr(host.Path, "home", lambda: tmp_path)
    now = 0.0

    def sleep(seconds):
        nonlocal now
        now += seconds

    monkeypatch.setattr(host, "time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    path = tmp_path / "Library/LaunchAgents" / f"{host.LABEL}.plist"
    path.parent.mkdir(parents=True)
    original = plistlib.dumps({"Label": host.LABEL, "ProgramArguments": ["old-server"]})
    path.write_bytes(original)
    actions = Mock()
    monkeypatch.setattr(host, "run", actions.run)
    monkeypatch.setattr(host, "service_loaded", actions.loaded)
    monkeypatch.setattr(host, "matches", actions.matches)
    return actions, path, original


def test_activate_waits_until_the_old_service_is_removed(launch_agent, tmp_path):
    actions, path, _ = launch_agent
    actions.loaded.side_effect = [True, True, False]
    manifest = {"command": ["new-server"]}
    actions.matches.return_value = True

    host.activate(tmp_path, manifest)

    assert actions.mock_calls[1:] == [
        call.loaded(TARGET),
        call.run("launchctl", "bootout", TARGET),
        call.loaded(TARGET),
        call.loaded(TARGET),
        call.run("launchctl", "bootstrap", DOMAIN, str(path), capture_output=True, text=True),
        call.matches(manifest),
    ]
    assert plistlib.loads(path.read_bytes())["ProgramArguments"] == ["new-server"]


def test_failed_warmup_waits_before_restoring_the_old_service(launch_agent, tmp_path):
    actions, path, original = launch_agent
    actions.loaded.side_effect = [True, False, True, True, False]
    actions.matches.return_value = False
    bootstrapped = []

    def run(*args, **kwargs):
        if args[1] == "bootstrap":
            bootstrapped.append(plistlib.loads(path.read_bytes())["ProgramArguments"])

    actions.run.side_effect = run

    with pytest.raises(ValueError, match="MPS service is not ready"):
        host.activate(tmp_path, {"command": ["new-server"]})

    assert path.read_bytes() == original
    assert bootstrapped == [["new-server"], ["old-server"]]
    assert actions.mock_calls[-5:] == [
        call.loaded(TARGET),
        call.run("launchctl", "bootout", TARGET),
        call.loaded(TARGET),
        call.loaded(TARGET),
        call.run("launchctl", "bootstrap", DOMAIN, str(path), capture_output=True, text=True),
    ]


def test_unload_timeout_leaves_the_old_configuration_in_place(launch_agent, tmp_path):
    actions, path, original = launch_agent
    actions.loaded.return_value = True

    with pytest.raises(ValueError, match="卸载超时"):
        host.activate(tmp_path, {"command": ["new-server"]})

    assert path.read_bytes() == original
    assert [entry.args[1] for entry in actions.run.call_args_list] == ["print", "bootout"]


@pytest.mark.parametrize("registered,attempts", [(False, 2), (True, 1)])
def test_bootstrap_retries_io_only_while_the_service_is_absent(launch_agent, registered, attempts):
    actions, path, _ = launch_agent
    args = ("launchctl", "bootstrap", DOMAIN, str(path))
    actions.run.side_effect = [subprocess.CalledProcessError(errno.EIO, args, stderr="Input/output error"), None]
    actions.loaded.return_value = registered

    if registered:
        with pytest.raises(ValueError, match="Input/output error"):
            host.bootstrap_agent(DOMAIN, TARGET, path)
    else:
        host.bootstrap_agent(DOMAIN, TARGET, path)
    assert actions.run.call_count == attempts


def test_service_probe_distinguishes_an_absent_service_from_other_errors(monkeypatch):
    command = ("launchctl", "print", TARGET)
    responses = [
        subprocess.CompletedProcess(command, 113, "", f'Could not find service "{host.LABEL}"'),
        subprocess.CompletedProcess(command, 1, "", "Operation not permitted"),
    ]
    monkeypatch.setattr(host.subprocess, "run", Mock(side_effect=responses))
    assert host.service_loaded(TARGET) is False
    with pytest.raises(subprocess.CalledProcessError):
        host.service_loaded(TARGET)

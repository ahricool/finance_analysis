#!/usr/bin/env python3
"""Prepare and supervise the isolated macOS MPS service used by production Compose."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SOURCE_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
LABEL = "cool.ahri.finance-analysis.kronos"
UNLOAD_TIMEOUT_SECONDS = 15
BOOTSTRAP_RETRY_SECONDS = 3
LAUNCHCTL_POLL_SECONDS = 0.2
CHECKPOINTS = {
    "small": ("Kronos-small", "901c26c1332695a2a8f243eb2f37243a37bea320",
              "b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020"),
    "base": ("Kronos-base", "2b554741eca47781b64468546e77fef3e85130e6",
             "abff193acab6db1a0368e9773e75799d11403b6d054ee6d5f0a11aeabc5f4b83"),
}
TOKENIZER = ("Kronos-Tokenizer-base", "0e0117387f39004a9016484a186a908917e22426",
             "59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, body: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def checkpoint(state: Path, spec: tuple[str, str, str]) -> Path:
    name, revision, digest = spec
    directory = state / "weights" / name / revision
    directory.mkdir(parents=True, exist_ok=True)
    weights = directory / "model.safetensors"
    config = directory / "config.json"
    if config.is_file() and weights.is_file() and sha256(weights) == digest:
        return directory
    for filename in ("config.json", "model.safetensors"):
        temporary = directory / (filename + ".part")
        url = f"https://huggingface.co/NeoQuasar/{name}/resolve/{revision}/{filename}?download=true"
        run("curl", "-fLsS", "--connect-timeout", "15", "--max-time", "600", "--retry", "2", url,
            "--output", str(temporary))
        if filename == "model.safetensors" and sha256(temporary) != digest:
            raise ValueError(f"Kronos weight checksum mismatch: {name}")
        temporary.replace(directory / filename)
    return directory


def model_checkpoint(state: Path, model: str) -> tuple[Path, str]:
    if model in CHECKPOINTS:
        spec = CHECKPOINTS[model]
        return checkpoint(state, spec), spec[1]
    source = os.environ.get("KRONOS_LARGE_CHECKPOINT")
    if not source:
        raise ValueError("Large has no public weights; set KRONOS_LARGE_CHECKPOINT to the checkpoint directory")
    checkpoint_dir = Path(source).expanduser().resolve()
    config = (checkpoint_dir / "config.json").read_bytes()
    weights = checkpoint_dir / "model.safetensors"
    weight_hash = sha256(weights)
    revision = hashlib.sha256(config + weight_hash.encode()).hexdigest()
    directory = state / "weights" / "Kronos-large" / revision
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / "model.safetensors").is_file() or sha256(directory / "model.safetensors") != weight_hash:
        temporary = directory / "model.safetensors.part"
        shutil.copyfile(weights, temporary)
        if sha256(temporary) != weight_hash:
            raise ValueError("Large checkpoint changed during preparation")
        temporary.replace(directory / "model.safetensors")
    atomic_write(directory / "config.json", config)
    return directory, revision


def prepare(root: Path, state: Path, model: str, port: int) -> dict:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Managed Kronos requires a macOS ARM64 host")
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    project = root / "kronos_worker"
    lock = (project / "uv.lock").read_bytes()
    source = state / f"source-{SOURCE_COMMIT}"
    if not source.is_dir():
        with tempfile.TemporaryDirectory(dir=state) as temporary:
            checkout = Path(temporary) / "source"
            run("git", "init", "-q", str(checkout))
            run("git", "-C", str(checkout), "fetch", "-q", "--depth", "1",
                "https://github.com/shiyu-coder/Kronos.git", SOURCE_COMMIT)
            run("git", "-C", str(checkout), "checkout", "-q", "--detach", "FETCH_HEAD")
            checkout.rename(source)
    model_dir, revision = model_checkpoint(state, model)
    tokenizer = checkpoint(state, TOKENIZER)
    runtime = state / ("venv-" + hashlib.sha256(lock).hexdigest()[:16])
    python = runtime / "bin/python"
    ready = runtime / ".ready"
    if not ready.is_file() or not python.is_file():
        uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
        run(uv, "sync", "--locked", "--no-dev", "--project", str(project),
            env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(runtime)})
        ready.touch()
    code = (project / "server.py").read_bytes()
    release = hashlib.sha256(code + lock + SOURCE_COMMIT.encode()).hexdigest()[:20]
    entry = state / f"server-{release}.py"
    atomic_write(entry, code)
    return {
        "protocol": 1, "device": "mps", "model": model, "weights_revision": revision,
        "release": release, "port": port,
        "command": [str(python), str(entry), "--source", str(source), "--model-dir", str(model_dir),
                    "--tokenizer-dir", str(tokenizer), "--model", model, "--weights-revision", revision,
                    "--release", release, "--port", str(port)],
    }


def matches(manifest: dict) -> bool:
    try:
        url = f"http://127.0.0.1:{manifest['port']}/healthz"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=2) as response:
            actual = json.load(response)
        return all(actual.get(key) == manifest[key] for key in
                   ("protocol", "device", "model", "weights_revision", "release"))
    except (OSError, ValueError, AttributeError):
        return False


def service_loaded(target: str) -> bool:
    result = subprocess.run(("launchctl", "print", target), capture_output=True, text=True)
    if result.returncode and "Could not find service" in result.stderr:
        return False
    result.check_returncode()
    return True


def wait_until_unloaded(target: str) -> None:
    deadline = time.monotonic() + UNLOAD_TIMEOUT_SECONDS
    while service_loaded(target):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError(f"Kronos LaunchAgent 卸载超时: {target}")
        time.sleep(min(remaining, LAUNCHCTL_POLL_SECONDS))


def bootstrap_agent(domain: str, target: str, path: Path) -> None:
    deadline = time.monotonic() + BOOTSTRAP_RETRY_SECONDS
    while True:
        try:
            run("launchctl", "bootstrap", domain, str(path), capture_output=True, text=True)
            return
        except subprocess.CalledProcessError as exc:
            remaining = deadline - time.monotonic()
            # launchctl can still report EIO while launchd finishes removing the prior registration.
            if exc.returncode != errno.EIO or remaining <= 0 or service_loaded(target):
                raise ValueError(f"Kronos LaunchAgent 注册失败: {(exc.stderr or '').strip() or exc}") from exc
            time.sleep(min(remaining, LAUNCHCTL_POLL_SECONDS))


def activate(state: Path, manifest: dict) -> None:
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{LABEL}"
    # LaunchAgents belong to the login session. Validate it before changing a
    # working service or pausing the container deployment.
    run("launchctl", "print", domain, stdout=subprocess.DEVNULL)
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    setup = plistlib.dumps({
        "Label": LABEL, "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "WorkingDirectory": str(state), "ProgramArguments": manifest["command"],
        "StandardOutPath": str(state / "kronos.log"), "StandardErrorPath": str(state / "kronos.log"),
        "EnvironmentVariables": {"HF_HUB_OFFLINE": "1", "PYTORCH_ENABLE_MPS_FALLBACK": "0",
                                 "PYTHONUNBUFFERED": "1"},
    })
    previous = path.read_bytes() if path.is_file() else None

    was_loaded = service_loaded(target)
    if previous == setup and was_loaded and matches(manifest):
        return
    unload_requested = False
    setup_written = False
    try:
        if was_loaded:
            run("launchctl", "bootout", target)
            unload_requested = True
            wait_until_unloaded(target)
        atomic_write(path, setup)
        setup_written = True
        bootstrap_agent(domain, target, path)
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            if matches(manifest):
                return
            time.sleep(1)
        raise ValueError(f"MPS service is not ready; see {state / 'kronos.log'}")
    except BaseException as exc:
        # A bad checkpoint or failed startup should leave the previous agent
        # available to the still-running application.
        try:
            if setup_written:
                if service_loaded(target):
                    run("launchctl", "bootout", target)
                wait_until_unloaded(target)
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, previous)
            if unload_requested and previous is not None:
                if not setup_written:
                    wait_until_unloaded(target)
                bootstrap_agent(domain, target, path)
        except (OSError, ValueError, subprocess.SubprocessError) as restore_error:
            raise ValueError(f"{exc}；恢复旧的 Kronos LaunchAgent 失败: {restore_error}") from exc
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--model", choices=("small", "base", "large"), default="small")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    state = args.state.resolve()
    try:
        manifest = prepare(Path(__file__).resolve().parents[1], state, args.model, args.port)
        if not args.prepare_only:
            activate(state, manifest)
        atomic_write(state / "manifest.json", json.dumps(manifest).encode())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Kronos 部署失败: {exc}\n")


if __name__ == "__main__":
    main()

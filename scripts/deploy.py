#!/usr/bin/env python3
"""Graceful, serialized production deployments (host Python >= 3.10, stdlib only)."""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

APP_SERVICES = ("server", "worker", "qlib-worker", "streamer", "web", "beat")
WORKERS = ("worker", "qlib-worker")
READ_COMMANDS = ("logs", "ps", "images", "top", "version", "ls")
INSPECT_FORMAT = (
    '{"id":"{{.Id}}","image":"{{.Image}}","state":{{json .State}},'
    '"command":{{json .Config.Cmd}},"stop_signal":{{json (index .Config "StopSignal")}}}'
)


class DeployError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> datetime:
    # Docker emits RFC3339Nano with Z. Normalize both for host Python 3.10,
    # whose fromisoformat accepts a narrower format than newer Python versions.
    normalized = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    return datetime.fromisoformat(normalized)


def write_json(path: Path, value: dict) -> None:
    """Atomic journal updates, including across an interrupted deployment."""
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class Deployment:
    def __init__(self, root: Path):
        self.root = root
        git_path = self.run("git", "rev-parse", "--git-path", "finance-deploy", capture=True).strip()
        self.directory = (root / git_path).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.pending_path = self.directory / "pending.json"
        self.release_path = self.directory / "release.json"
        self.override_path = self.directory / "target-compose.json"
        self.pending: dict = {}
        self.env = os.environ.copy()
        self.wait_timeout = self.positive_seconds("DEPLOY_READY_TIMEOUT", 300)
        self.warn_after = self.positive_seconds("DEPLOY_DRAIN_WARN_SECONDS", 900)

    @staticmethod
    def positive_seconds(name: str, default: int) -> int:
        try:
            value = int(os.environ.get(name, default))
        except ValueError as exc:
            raise DeployError(f"{name} 必须是正整数") from exc
        if value <= 0:
            raise DeployError(f"{name} 必须是正整数")
        return value

    def log(self, message: str) -> None:
        line = f"[{utc_now()}] {message}"
        print(line, flush=True)
        with (self.directory / "deploy.log").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def run(self, *args: str, capture: bool = False, timeout: int | None = None) -> str:
        process = subprocess.Popen(
            args, cwd=self.root, env=getattr(self, "env", None),
            stdout=subprocess.PIPE if capture else None, text=True, start_new_session=True,
        )
        try:
            output, _ = process.communicate(timeout=timeout)
        except BaseException:
            # Isolate CLI signal handlers: Ctrl-C must not make Compose shut down
            # new workers that have already begun consuming tasks. Only terminate
            # this host CLI group; container processes belong to the Docker daemon.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, args)
        return output or ""

    def compose(self, *args: str, target: bool = False, capture: bool = False) -> str:
        command = ["docker", "compose", "-f", "docker-compose.prod.yml"]
        if target:
            command.extend(("-f", str(self.override_path)))
        return self.run(*command, *args, capture=capture)

    @contextmanager
    def lock(self):
        with (self.directory / "lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DeployError("已有部署/维护命令运行；使用 bash deploy.sh --status 查看进度") from exc
            yield

    def inspect(self, container_id: str) -> dict:
        return json.loads(self.run("docker", "inspect", "--format", INSPECT_FORMAT, container_id, capture=True))

    def containers(self, services: tuple[str, ...]) -> dict:
        result = {}
        for service in services:
            ids = self.compose("ps", "--all", "--quiet", service, capture=True).split()
            if len(ids) > 1:
                raise DeployError(f"{service} 存在多个容器，当前脚本仅支持单实例 Compose")
            if ids:
                result[service] = self.inspect(ids[0])
        return result

    def check_infrastructure(self) -> None:
        containers = self.containers(("postgres", "redis"))
        for service in ("postgres", "redis"):
            state = containers.get(service, {}).get("state", {})
            if not state.get("Running") or state.get("Health", {}).get("Status") != "healthy":
                raise DeployError(f"{service} 必须已启动且健康；基础设施请单独维护")

    def phase(self, phase: str) -> None:
        self.pending["phase"] = phase
        self.pending["updated_at"] = utc_now()
        write_json(self.pending_path, self.pending)
        self.log(f"阶段: {phase}")

    def prepare(self) -> None:
        if self.run("git", "status", "--porcelain", capture=True).strip():
            raise DeployError("工作区存在未提交改动，请先提交后再部署")
        self.run("git", "checkout", "main")
        self.run("git", "pull", "--ff-only", "origin", "main")
        revision = self.run("git", "rev-parse", "HEAD", capture=True).strip()
        self.env["IMAGE_TAG"] = f"sha-{revision}"
        # Capture config privately: it includes database credentials; never log it.
        config = json.loads(self.compose("config", "--format", "json", capture=True))
        self.check_infrastructure()
        self.log(f"拉取发布镜像: sha-{revision}")
        self.compose("pull", *APP_SERVICES)
        images = {}
        image_ids = {}
        for service in APP_SERVICES:
            image = config["services"][service]["image"]
            image_info = json.loads(self.run(
                "docker", "image", "inspect", "--format",
                '{"id":"{{.Id}}","revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
                '"digests":{{json .RepoDigests}}}', image, capture=True,
            ))
            if image_info["revision"] != revision:
                raise DeployError(f"{service} 镜像 revision 与发布提交不一致")
            repository = image.rsplit(":", 1)[0]
            digest = next((item for item in image_info["digests"] or [] if item.startswith(repository + "@")), None)
            if digest is None:
                raise DeployError(f"{service} 镜像缺少 registry digest")
            images[service] = {"image": digest}
            image_ids[service] = image_info["id"]
        write_json(self.override_path, {"services": images})
        old = self.containers(APP_SERVICES)
        for service in WORKERS:
            if service in old and old[service]["stop_signal"] not in (None, "", "SIGTERM", "15"):
                raise DeployError(f"{service} stop signal 不是 SIGTERM，拒绝停止")
            if service in old and old[service]["state"].get("Running"):
                app = "qlib_worker.celery_app" if service == "qlib-worker" else "finance_analysis.tasks.celery.app"
                remapped = self.run(
                    "docker", "exec", old[service]["id"], "python", "-c",
                    f"import os; from {app} import celery_app; print(os.environ.get('REMAP_SIGTERM') == 'SIGQUIT')",
                    capture=True,
                ).strip()
                if remapped == "True":
                    raise DeployError(f"{service} 将 SIGTERM 映射到了强制停止，拒绝部署")
        self.pending = {
            "revision": revision, "tag": self.env["IMAGE_TAG"], "images": images, "image_ids": image_ids,
            "started_at": utc_now(),
        }

    def stop(self, ids: list[str]) -> None:
        if not ids:
            return
        # Docker marks this as a manual stop, suppressing automatic restarts.
        # -1 disables Docker's SIGKILL deadline, including on legacy containers.
        process = subprocess.Popen(
            ["docker", "stop", "--timeout", "-1", *ids], cwd=self.root, env=self.env,
            start_new_session=True,
        )
        started = time.monotonic()
        next_warning = self.warn_after
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= next_warning:
                    self.log(f"仍在等待旧容器优雅退出（{int(elapsed)}s）；不会强杀任务，可用 --status 查看")
                    next_warning += self.warn_after
                time.sleep(2)
            if process.returncode:
                raise DeployError("Docker 优雅停止失败")
        finally:
            if process.poll() is None:
                # Only disconnect the CLI; never signal the container/task here.
                process.terminate()
                process.wait(timeout=10)
        for container_id in ids:
            state = self.inspect(container_id)["state"]
            if state.get("Running") or state.get("OOMKilled") or state.get("ExitCode") != 0:
                raise DeployError(f"旧容器 {container_id[:12]} 未正常退出，停止推进部署")

    def drain(self) -> None:
        current = self.containers(APP_SERVICES)
        self.pending.setdefault("paused_at", utc_now())
        self.phase("pausing")
        beat = current.get("beat")
        self.stop([beat["id"]] if beat else [])
        self.phase("draining")
        worker_ids = [
            current[name]["id"] for name in WORKERS if name in current
        ]
        self.stop(worker_ids)
        self.phase("drained")

    def up(self, services: tuple[str, ...], *, force_recreate: bool = False) -> None:
        recreate = ("--force-recreate",) if force_recreate else ()
        self.compose(
            "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait",
            "--wait-timeout", str(self.wait_timeout), *recreate, *services, target=True,
        )

    def verify_apps(self, services: tuple[str, ...]) -> None:
        containers = self.containers(services)
        for service in services:
            container = containers.get(service, {})
            state = container.get("state", {})
            if container.get("image") != self.pending["image_ids"][service] or not state.get("Running"):
                raise DeployError(f"{service} 未运行目标镜像")
            if service != "streamer" and state.get("Health", {}).get("Status") != "healthy":
                raise DeployError(f"{service} 未通过健康检查")

    def replace(self) -> None:
        self.phase("replacing")
        self.compose("stop", "server", "streamer")
        self.compose(
            "run", "--rm", "--no-deps", "--pull", "never", "server", "python", "-c",
            "from finance_analysis.database.session import DatabaseManager; DatabaseManager.get_instance()",
            target=True,
        )
        self.up(("server",))
        self.up(("worker", "qlib-worker", "streamer", "web"))
        self.verify_apps(APP_SERVICES[:-1])
        self.pending["beat_starting_at"] = utc_now()
        self.phase("starting_beat")
        # Even a same-revision deployment starts Beat with fresh ephemeral state;
        # do not carry last_run_at across the deployment pause or replay missed fires.
        self.up(("beat",), force_recreate=True)
        self.pending["resumed_at"] = self.containers(("beat",))["beat"]["state"]["StartedAt"]
        self.verify_beat()
        self.verify_apps(APP_SERVICES)
        self.phase("verifying")
        self.pending["completed_at"] = utc_now()
        self.pending["phase"] = "complete"
        write_json(self.release_path, self.pending)
        self.pending_path.unlink()
        self.log("✅ 生产环境部署完成；旧任务正常退出，新版本健康，Beat 已恢复")

    def verify_beat(self) -> None:
        # A previous Beat's TTL can still be present; require a NEW heartbeat.
        since = parse_timestamp(self.pending["resumed_at"])
        deadline = time.monotonic() + min(self.wait_timeout, 90)
        while time.monotonic() < deadline:
            output = self.compose(
                "exec", "-T", "server", "python", "-c",
                "from finance_analysis.tasks.celery.schedule.heartbeat import _redis_client,HEARTBEAT_KEY; "
                "value=_redis_client().get(HEARTBEAT_KEY); print(value.decode() if value else '')",
                target=True, capture=True,
            ).strip()
            if output and parse_timestamp(output) >= since:
                return
            time.sleep(2)
        raise DeployError("Beat 未写入新的心跳，拒绝宣布部署成功")

    def execute(self, args: list[str]) -> None:
        if args == ["--status"]:
            path = self.pending_path if self.pending_path.exists() else self.release_path
            print(path.read_text() if path.exists() else "尚无部署记录")
            return
        if args and args[0] in READ_COMMANDS:
            # Logs/status must remain available during an hours-long drain. These
            # Compose commands never change containers or deployment manifests.
            self.compose(*args)
            return
        with self.lock():
            if args == ["--recover"]:
                raise DeployError("不再恢复旧版本；修复后运行 bash deploy.sh 部署最新 main")
            if args and args != ["--resume"]:
                if args[0].startswith("--"):
                    raise DeployError("Usage: bash deploy.sh [--status|--resume|COMPOSE_ARGS]")
                # Explicit maintenance uses the most recently attempted release,
                # not an older successful release after a partial replacement.
                path = self.pending_path if self.pending_path.exists() else self.release_path
                if path.exists():
                    release = json.loads(path.read_text())
                    self.env["IMAGE_TAG"] = release["tag"]
                    write_json(self.override_path, {"services": release["images"]})
                    self.compose(*args, target=True)
                else:
                    self.compose(*args)
                return
            # A journal is diagnostic only. Every retry prepares the latest main
            # and drains the current containers, including partially deployed ones.
            # Keep --resume as an alias for existing operators/runbooks.
            self.prepare()
            try:
                self.drain()
                self.replace()
            except BaseException:
                # On interruption/partial replacement, keep the journal and avoid
                # unconditionally restarting Beat against a mixed deployment.
                self.log("部署未完成；使用 --status 查看阶段，修复后重新运行 bash deploy.sh 部署最新 main")
                if self.pending.get("beat_starting_at"):
                    # Startup can fail AFTER Beat began publishing. Leave it paused
                    # until the next deployment verifies the complete release.
                    self.compose("stop", "beat")
                raise


def main() -> int:
    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        Deployment(Path(__file__).resolve().parents[1]).execute(sys.argv[1:])
        return 0
    except (DeployError, subprocess.SubprocessError, OSError, ValueError, KeyboardInterrupt) as exc:
        print(f"❌ {exc or '部署已中断'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

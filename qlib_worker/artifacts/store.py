"""Traversal-safe, atomic and retry-idempotent artifact storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for_uri(self, uri: str, *, must_exist: bool = True) -> Path:
        if not isinstance(uri, str) or not uri.startswith("quant://"):
            raise ValueError("artifact URI must use quant://")
        relative = uri.removeprefix("quant://")
        if not relative or Path(relative).is_absolute():
            raise ValueError("artifact URI must contain a relative path")
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("artifact path traversal rejected")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(f"Artifact does not exist: {uri}")
        return candidate

    def model_uri(self, model_key: str, model_version: str, model_run_id: int) -> str:
        for value, label in ((model_key, "model_key"), (model_version, "model_version")):
            if not value or value in {".", ".."} or "/" in value or "\\" in value:
                raise ValueError(f"Invalid {label}")
        return f"quant://models/{model_key}/{model_version}/{model_run_id}"

    def commit_model(
        self,
        uri: str,
        request_digest: str,
        writer: Callable[[Path], dict[str, Any]],
    ) -> dict[str, Any]:
        final = self.path_for_uri(uri, must_exist=False)
        existing = self._existing_result(final, request_digest)
        if existing is not None:
            return existing
        final.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
        try:
            result = writer(temporary)
            required = {"model.joblib", "metadata.json", "metrics.json", "test_predictions.parquet"}
            missing = sorted(name for name in required if not (temporary / name).is_file())
            if missing:
                raise RuntimeError(f"Incomplete model artifact; missing {missing}")
            digest, size = self._tree_digest(temporary)
            result = {**result, "artifact_uri": uri, "artifact_digest": digest, "artifact_size": size}
            self._write_json(temporary / "result.json", result)
            self._write_json(
                temporary / "artifact_manifest.json",
                {"schema_version": 1, "request_digest": request_digest, "digest": digest, "size": size},
            )
            try:
                os.rename(temporary, final)
            except FileExistsError:
                existing = self._existing_result(final, request_digest)
                if existing is None:
                    raise RuntimeError(f"Artifact destination already exists with different content: {uri}")
                return existing
            return result
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def inspect(self, uri: str) -> dict[str, Any]:
        path = self.path_for_uri(uri)
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            return {"artifact_uri": uri, "kind": "file", "digest": digest, "size": path.stat().st_size}
        manifest = path / "artifact_manifest.json"
        if manifest.exists():
            return {"artifact_uri": uri, "kind": "directory", **json.loads(manifest.read_text())}
        digest, size = self._tree_digest(path)
        return {"artifact_uri": uri, "kind": "directory", "digest": digest, "size": size}

    @staticmethod
    def request_digest(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _tree_digest(root: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix().encode()
            data = path.read_bytes()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(data)
            size += len(data)
        return digest.hexdigest(), size

    @staticmethod
    def _existing_result(path: Path, request_digest: str) -> dict[str, Any] | None:
        manifest_path = path / "artifact_manifest.json"
        result_path = path / "result.json"
        if not manifest_path.is_file() or not result_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("request_digest") != request_digest:
            return None
        return json.loads(result_path.read_text(encoding="utf-8"))

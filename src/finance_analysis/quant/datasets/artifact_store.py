"""Filesystem artifact store with traversal protection and content digests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.exceptions import ModelArtifactMissingError


class ArtifactStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or get_quant_config().artifact_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Artifact path escapes QUANT_ARTIFACT_ROOT")
        return candidate

    def directory(self, relative: str) -> Path:
        target = self.path(relative); target.mkdir(parents=True, exist_ok=True); return target

    def write_json(self, relative: str, payload: Any) -> dict:
        target = self.path(relative); target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str).encode()
        target.write_bytes(data)
        return {"artifact_uri": f"quant://{relative}", "digest": hashlib.sha256(data).hexdigest(), "size": len(data)}

    def resolve_uri(self, uri: str) -> Path:
        if not uri.startswith("quant://"): raise ValueError("Unsupported artifact URI")
        target = self.path(uri.removeprefix("quant://"))
        if not target.exists(): raise ModelArtifactMissingError(f"Artifact does not exist: {uri}")
        return target

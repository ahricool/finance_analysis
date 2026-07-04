"""Runtime configuration for the isolated Qlib process."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkerConfig:
    redis_url: str
    artifact_root: Path


def get_worker_config() -> WorkerConfig:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL is required")
    if os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL must not be provided to the Qlib worker")
    return WorkerConfig(
        redis_url=redis_url,
        artifact_root=Path(os.getenv("QUANT_ARTIFACT_ROOT", "/workspace/data/quant")).resolve(),
    )

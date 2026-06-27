# -*- coding: utf-8 -*-
"""Execution lock for A-share intraday analysis runs."""

from __future__ import annotations

import errno
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

logger = logging.getLogger(__name__)
_lock_guard = threading.Lock()
_running_keys: set[str] = set()
RUNNING_LOCK_KEY = "a_share_intraday:running"


@dataclass
class AShareIntradayExecutionLock:
    key: str
    handle: Any
    path: Path
    uses_flock: bool


def _lock_path(key: str) -> Path:
    from finance_analysis.core.paths import get_runtime_locks_dir

    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", key.strip())
    return get_runtime_locks_dir() / f"{safe_key}.lock"


def _write_metadata(handle: Any, key: str) -> None:
    handle.seek(0)
    handle.truncate()
    handle.write(f"key={key}\npid={os.getpid()}\nstarted_at={datetime.now().isoformat()}\n")
    handle.flush()


def try_acquire_a_share_intraday_lock(key: str) -> Optional[AShareIntradayExecutionLock]:
    """Acquire a same-host global running lock and record the requested window."""
    window_key = key.strip()
    lock_path = _lock_path(RUNNING_LOCK_KEY)
    with _lock_guard:
        if RUNNING_LOCK_KEY in _running_keys:
            return None
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        if fcntl is not None:
            handle = open(lock_path, "a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                handle.close()
                if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (
                    errno.EACCES,
                    errno.EAGAIN,
                ):
                    return None
                raise
            uses_flock = True
        else:  # pragma: no cover - exercised only on platforms without fcntl
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError:
                return None
            handle = os.fdopen(fd, "w+", encoding="utf-8")
            uses_flock = False

        _write_metadata(handle, window_key)
        _running_keys.add(RUNNING_LOCK_KEY)
        return AShareIntradayExecutionLock(
            key=RUNNING_LOCK_KEY,
            handle=handle,
            path=lock_path,
            uses_flock=uses_flock,
        )


def release_a_share_intraday_lock(lock_token: Optional[AShareIntradayExecutionLock]) -> None:
    if lock_token is None:
        return
    with _lock_guard:
        _running_keys.discard(lock_token.key)
    try:
        if lock_token.uses_flock and fcntl is not None:
            fcntl.flock(lock_token.handle.fileno(), fcntl.LOCK_UN)
    finally:
        lock_token.handle.close()
        if not lock_token.uses_flock:
            try:
                lock_token.path.unlink()
            except FileNotFoundError:
                pass

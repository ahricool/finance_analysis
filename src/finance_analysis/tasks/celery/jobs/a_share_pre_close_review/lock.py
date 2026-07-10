"""Same-host execution lock for the once-per-day pre-close review."""

from __future__ import annotations

import errno
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

_LOCK_KEY = "a_share_pre_close_review_running"
_guard = threading.Lock()
_running = False


@dataclass
class PreCloseReviewLock:
    handle: Any
    path: Path
    uses_flock: bool


def try_acquire_lock() -> Optional[PreCloseReviewLock]:
    global _running
    from finance_analysis.core.paths import get_runtime_locks_dir

    path = get_runtime_locks_dir() / f"{_LOCK_KEY}.lock"
    with _guard:
        if _running:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is not None:
            handle = open(path, "a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                handle.close()
                if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (errno.EACCES, errno.EAGAIN):
                    return None
                raise
            uses_flock = True
        else:  # pragma: no cover
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError:
                return None
            handle = os.fdopen(fd, "w+", encoding="utf-8")
            uses_flock = False
        _running = True
        return PreCloseReviewLock(handle=handle, path=path, uses_flock=uses_flock)


def release_lock(token: Optional[PreCloseReviewLock]) -> None:
    global _running
    if token is None:
        return
    with _guard:
        _running = False
    try:
        if token.uses_flock and fcntl is not None:
            fcntl.flock(token.handle.fileno(), fcntl.LOCK_UN)
    finally:
        token.handle.close()
        if not token.uses_flock:
            try:
                token.path.unlink()
            except FileNotFoundError:
                pass

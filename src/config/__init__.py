# -*- coding: utf-8 -*-
"""Environment bootstrap only.

Business configuration lives in the owning modules. This package only loads the
project ``.env`` once, without overriding process-provided environment values.
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_path() -> Path:
    configured = os.getenv("ENV_FILE")
    if configured:
        return Path(configured).expanduser()
    return _PROJECT_ROOT / ".env"


@lru_cache(maxsize=1)
def load_env() -> Path:
    """Load the active env file once and return its path.

    Precedence is process environment > ``.env`` > code defaults because
    ``override=False`` preserves any variables already present in ``os.environ``.
    """
    env_path = _env_path()
    load_dotenv(dotenv_path=env_path, override=False)
    return env_path


__all__ = ["load_env"]

# -*- coding: utf-8 -*-
"""Finance Analysis configuration package."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from finance_analysis.config.env_parsing import (
    env_bool,
    env_float,
    env_int,
    env_list,
    env_str,
)

from finance_analysis.core.paths import get_env_file_path

@lru_cache(maxsize=1)
def load_env() -> Path:
    """Load the active env file once and return its path."""
    env_path = get_env_file_path()
    load_dotenv(dotenv_path=env_path, override=False)
    return env_path

__all__ = [
    "env_bool",
    "env_float",
    "env_int",
    "env_list",
    "env_str",
    "load_dotenv",
    "load_env",
]

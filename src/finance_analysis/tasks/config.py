# -*- coding: utf-8 -*-
"""Task execution configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass
class TaskConfig:
    max_workers: int = 3


@lru_cache(maxsize=1)
def get_task_config() -> TaskConfig:
    return TaskConfig()

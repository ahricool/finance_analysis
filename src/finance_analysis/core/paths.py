# -*- coding: utf-8 -*-
"""Repository path helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import finance_analysis


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Return the repository root directory (parent of ``src/``)."""
    return Path(finance_analysis.__file__).resolve().parent.parent.parent


__all__ = ["repo_root"]

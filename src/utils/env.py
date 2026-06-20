# -*- coding: utf-8 -*-
"""Small helpers for reading typed environment values.

These functions intentionally do not load ``.env`` and do not know any business
defaults. Callers pass their own defaults from the owning module.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_FALSE_VALUES = {"0", "false", "no", "off"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    logger.warning("%s=%r is not a valid boolean; falling back to %s", name, value, default)
    return default


def env_int(
    name: str,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        parsed = int(default)
    else:
        try:
            parsed = int(value.strip())
        except (TypeError, ValueError):
            logger.warning("%s=%r is not a valid integer; falling back to %s", name, value, default)
            parsed = int(default)
    if minimum is not None and parsed < minimum:
        logger.warning("%s=%r is below minimum %s; clamping to %s", name, parsed, minimum, minimum)
        parsed = minimum
    if maximum is not None and parsed > maximum:
        logger.warning("%s=%r is above maximum %s; clamping to %s", name, parsed, maximum, maximum)
        parsed = maximum
    return parsed


def env_float(
    name: str,
    default: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        parsed = float(default)
    else:
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError):
            logger.warning("%s=%r is not a valid number; falling back to %s", name, value, default)
            parsed = float(default)
    if minimum is not None and parsed < minimum:
        logger.warning("%s=%r is below minimum %s; clamping to %s", name, parsed, minimum, minimum)
        parsed = minimum
    if maximum is not None and parsed > maximum:
        logger.warning("%s=%r is above maximum %s; clamping to %s", name, parsed, maximum, maximum)
        parsed = maximum
    return parsed


def env_list(name: str, default: Optional[list[str]] = None) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]

# -*- coding: utf-8 -*-
"""SQLAlchemy declarative base and shared storage normalization helpers."""

from datetime import date, datetime, time, timezone
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import declarative_base

from src.time_utils import coerce_aware_utc


Base = declarative_base()


def ensure_aware_datetime(value: Optional[Any]) -> Optional[datetime]:
    """Normalize datetime/date values to timezone-aware UTC datetimes."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return coerce_aware_utc(value)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    return None

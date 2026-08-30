"""Trend Following API write contracts."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class TrendFollowingRunRequest(BaseModel):
    market: Literal["CN", "US"] = "CN"
    trade_date: date | None = None


__all__ = ["TrendFollowingRunRequest"]

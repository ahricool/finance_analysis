"""ETF Rotation API write contracts."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class ETFRotationRunRequest(BaseModel):
    market: Literal["CN", "US"] = "CN"
    trade_date: date | None = None


__all__ = ["ETFRotationRunRequest"]

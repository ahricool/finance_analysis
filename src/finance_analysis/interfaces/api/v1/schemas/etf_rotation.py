"""ETF Rotation API write contracts."""

from datetime import date

from pydantic import BaseModel


class ETFRotationRunRequest(BaseModel):
    trade_date: date | None = None


__all__ = ["ETFRotationRunRequest"]

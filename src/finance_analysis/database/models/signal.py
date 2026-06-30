"""Persisted analysis signals and their forward performance evaluations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class Signal(Base):
    """A point-in-time market signal with incrementally populated evaluations."""

    __tablename__ = "signal"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False)
    code = Column(String(16), nullable=False)
    name = Column(String(80), nullable=True)
    signal_type = Column(String(80), nullable=True)
    price = Column(Float, nullable=False)
    signal_at = Column(DateTime(timezone=True), nullable=False, index=True)
    evaluation = Column(
        MutableDict.as_mutable(JSON().with_variant(JSONB, "postgresql")),
        nullable=False,
        default=dict,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        CheckConstraint("market IN ('CN', 'US', 'HK')", name="ck_signal_market"),
        Index("ix_signal_market_signal_at_id", "market", "signal_at", "id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "market": self.market,
            "code": self.code,
            "name": self.name,
            "signal_type": self.signal_type,
            "price": self.price,
            "signal_at": self.signal_at.isoformat() if self.signal_at else None,
            "evaluation": dict(self.evaluation or {}),
        }

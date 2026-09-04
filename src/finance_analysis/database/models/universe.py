"""Unified current-time market, index, and strategy universes."""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base

JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class Universe(Base):
    __tablename__ = "universe"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    market = Column(String(8), nullable=False)
    universe_type = Column(String(16), nullable=False, default="INDEX")
    enabled = Column(Boolean, nullable=False, default=True)
    config = Column(JSON_TYPE, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    members = relationship("UniverseMember", cascade="all, delete-orphan", back_populates="universe")
    includes = relationship(
        "UniverseInclude", cascade="all, delete-orphan", back_populates="universe",
        foreign_keys="UniverseInclude.universe_id",
    )

    __table_args__ = (
        CheckConstraint("market IN ('US','HK','CN')", name="ck_universe_market"),
        CheckConstraint("universe_type IN ('MARKET','INDEX','STRATEGY')", name="ck_universe_type"),
    )


class UniverseMember(Base):
    __tablename__ = "universe_member"

    id = Column(Integer, primary_key=True, autoincrement=True)
    universe_id = Column(Integer, ForeignKey("universe.id", ondelete="CASCADE"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(32), nullable=False)
    member_metadata = Column("metadata", JSON_TYPE, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    universe = relationship("Universe", back_populates="members")
    instrument = relationship("Instrument", lazy="joined")

    __table_args__ = (UniqueConstraint("universe_id", "instrument_id", name="uix_universe_member"),)


class UniverseInclude(Base):
    __tablename__ = "universe_include"

    id = Column(Integer, primary_key=True, autoincrement=True)
    universe_id = Column(Integer, ForeignKey("universe.id", ondelete="CASCADE"), nullable=False)
    included_universe_id = Column(Integer, ForeignKey("universe.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    universe = relationship("Universe", foreign_keys=[universe_id], back_populates="includes")
    included_universe = relationship("Universe", foreign_keys=[included_universe_id])

    __table_args__ = (
        UniqueConstraint("universe_id", "included_universe_id", name="uix_universe_include"),
        CheckConstraint("universe_id <> included_universe_id", name="ck_universe_include_not_self"),
    )


__all__ = ["Universe", "UniverseInclude", "UniverseMember"]

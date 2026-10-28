"""Disposable latest-only research, separate from official strategy history."""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB

from finance_analysis.database.base import Base

JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class ResearchPreview(Base):
    __tablename__ = "research_preview"

    namespace = Column(String(32), primary_key=True)
    market = Column(String(8), primary_key=True)
    variant = Column(Integer, primary_key=True, default=0)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    header = Column(JSON_TYPE, nullable=False)
    shared = Column(JSON_TYPE, nullable=False)

    __table_args__ = (
        CheckConstraint("market IN ('CN', 'US')", name="ck_research_preview_market"),
        CheckConstraint("variant IN (0, 20, 40, 60)", name="ck_research_preview_variant"),
    )


class ResearchPreviewItem(Base):
    __tablename__ = "research_preview_item"

    namespace = Column(String(32), primary_key=True)
    market = Column(String(8), primary_key=True)
    variant = Column(Integer, primary_key=True)
    kind = Column(String(64), primary_key=True)
    item_key = Column(String(64), primary_key=True)
    position = Column(Integer, nullable=False)
    instrument_id = Column(Integer, ForeignKey("instrument.id", ondelete="SET NULL"))
    has_name = Column(Boolean, nullable=False, default=False)
    summary = Column(JSON_TYPE, nullable=False)
    detail = Column(JSON_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["namespace", "market", "variant"],
            ["research_preview.namespace", "research_preview.market", "research_preview.variant"],
            ondelete="CASCADE", name="fk_research_preview_item_batch",
        ),
    )

"""Durable frozen pool and latest evidence for each market trading day."""

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.database.base import Base


class IntradayConfirmationSnapshot(Base):
    __tablename__ = "intraday_confirmation_snapshot"
    market = Column(String(8), primary_key=True)
    trade_date = Column(Date, primary_key=True)
    payload = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    revision = Column(Integer, nullable=False)
    returns_pending = Column(Boolean, nullable=False, default=False)
    returns_checked_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("market IN ('CN','US')", name="ck_intraday_confirmation_market"),
        CheckConstraint("revision > 0", name="ck_intraday_confirmation_revision"),
    )


class IntradayConfirmationEvaluation(Base):
    """Compact immutable evaluation evidence; no raw minute history or user data."""

    __tablename__ = "intraday_confirmation_evaluation"
    market = Column(String(8), primary_key=True)
    trade_date = Column(Date, primary_key=True)
    evaluated_at = Column(DateTime(timezone=True), primary_key=True)
    rule_version = Column(String(32), nullable=False)
    payload = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    __table_args__ = (CheckConstraint("market IN ('CN','US')", name="ck_intraday_evaluation_market"),)

"""Shared US options research facts; user holdings/watch-list membership is never exposed."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    JSON,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Text,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now


def jt():
    return JSONB().with_variant(JSON(), "sqlite")


class OptionContract(Base):
    __tablename__ = "option_contract"
    symbol = Column(String(64), primary_key=True)
    underlying_symbol = Column(String(32), nullable=False, index=True)
    option_type = Column(String(4), nullable=False)
    expiration = Column(Date, nullable=False)
    strike = Column(Float, nullable=False)
    multiplier = Column(Float)
    __table_args__ = (CheckConstraint("option_type IN ('call','put')", name="ck_option_contract_type"),)


class OptionQuoteSnapshot(Base):
    # One bounded chain batch per symbol/30-minute bucket, rather than a million duplicate quote rows.
    __tablename__ = "option_quote_snapshot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    trade_date = Column(Date, nullable=False)
    bucket = Column(DateTime(timezone=True), nullable=False)
    mode = Column(String(16), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(jt(), nullable=False)  # source-isolated normalized observations, OI as-of included
    metrics = Column(jt(), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    __table_args__ = (
        UniqueConstraint("symbol", "bucket", "mode", name="uq_option_snapshot_bucket"),
        Index("ix_option_snapshot_symbol_date", "symbol", "trade_date"),
    )


class OptionDailyMetrics(Base):
    __tablename__ = "option_daily_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    trade_date = Column(Date, nullable=False)
    snapshot_id = Column(Integer, ForeignKey("option_quote_snapshot.id"), nullable=False)
    metrics = Column(jt(), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("symbol", "trade_date", name="uq_option_daily_symbol_date"),)


class OptionAnomalyEvent(Base):
    __tablename__ = "option_anomaly_event"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    contract_symbol = Column(String(64), nullable=False, default="")
    event_type = Column(String(40), nullable=False)
    trade_date = Column(Date, nullable=False)
    data_source = Column(String(16), nullable=False)
    feed_type = Column(String(16), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    initial_evidence = Column(jt(), nullable=False)
    latest_evidence = Column(jt(), nullable=False)
    changes = Column(jt(), nullable=False, default=list)
    validation = Column(jt(), nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "contract_symbol",
            "event_type",
            "trade_date",
            "data_source",
            "feed_type",
            name="uq_option_event_daily",
        ),
        Index("ix_option_event_symbol_date", "symbol", "trade_date"),
    )


class OptionAnalysis(Base):
    __tablename__ = "option_analysis"
    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("option_quote_snapshot.id"), nullable=False, unique=True)
    explanation = Column(jt(), nullable=False)
    model = Column(String(160))
    prompt = Column(Text, nullable=False)
    raw_response = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

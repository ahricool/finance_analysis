"""Persistence models for versioned quantitative research results.

PostgreSQL remains the source of truth.  Qlib datasets and model binaries are
referenced by URI and never stored in JSON columns.
"""

from __future__ import annotations

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship


def json_object():
    return {}


def json_array():
    return []


class QuantDatasetSnapshot(Base):
    __tablename__ = "quant_dataset_snapshot"
    id = Column(BigInteger, primary_key=True)
    dataset_key = Column(String(128), nullable=False, unique=True)
    market = Column(String(8), nullable=False)
    universe_id = Column(Integer, ForeignKey("universe.id", ondelete="RESTRICT"), nullable=False)
    frequency = Column(String(16), nullable=False)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    feature_version = Column(String(64), nullable=False)
    source_revision = Column(String(64), nullable=False)
    code_commit = Column(String(64))
    artifact_uri = Column(Text)
    row_count = Column(BigInteger, nullable=False, default=0)
    symbol_count = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="pending")
    validation_result = Column(JSONB, nullable=False, default=json_object)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('pending','building','ready','failed')", name="ck_quant_dataset_status"),
        CheckConstraint("date_to >= date_from", name="ck_quant_dataset_dates"),
        Index("ix_quant_dataset_lookup", "market", "universe_id", "created_at"),
    )


class MarketRegimeSnapshot(Base):
    __tablename__ = "market_regime_snapshot"
    id = Column(BigInteger, primary_key=True)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    model_version = Column(String(64), nullable=False)
    regime = Column(String(16), nullable=False)
    market_score = Column(Float, nullable=False)
    max_equity_exposure = Column(Float, nullable=False)
    features = Column(JSONB, nullable=False, default=json_object)
    reasons = Column(JSONB, nullable=False, default=json_array)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("market", "trade_date", "model_version", name="uix_market_regime_version"),
        CheckConstraint("regime IN ('risk_on','neutral','risk_off')", name="ck_market_regime_state"),
        Index("ix_market_regime_latest", "market", "trade_date"),
    )


class ModelDefinition(Base):
    __tablename__ = "model_definition"
    id = Column(Integer, primary_key=True)
    key = Column(String(80), nullable=False, unique=True)
    name = Column(String(160), nullable=False)
    model_type = Column(String(24), nullable=False)
    task_type = Column(String(24), nullable=False)
    frequency = Column(String(16), nullable=False)
    target_definition = Column(JSONB, nullable=False, default=json_object)
    enabled = Column(Boolean, nullable=False, default=True)
    default_config = Column(JSONB, nullable=False, default=json_object)
    supported_markets = Column(JSONB, nullable=False, default=json_array)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    __table_args__ = (
        CheckConstraint(
            "model_type IN ('market_regime','time_series','cross_section','fusion')", name="ck_model_definition_type"
        ),
    )


class ModelRun(Base):
    __tablename__ = "model_run"
    id = Column(BigInteger, primary_key=True)
    uid = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    task_id = Column(String(64))
    model_definition_id = Column(Integer, ForeignKey("model_definition.id", ondelete="RESTRICT"), nullable=False)
    model_key = Column(String(80), nullable=False)
    model_version = Column(String(96), nullable=False)
    run_type = Column(String(24), nullable=False)
    market = Column(String(8), nullable=False)
    universe_id = Column(Integer, ForeignKey("universe.id", ondelete="RESTRICT"), nullable=False)
    dataset_snapshot_id = Column(BigInteger, ForeignKey("quant_dataset_snapshot.id", ondelete="RESTRICT"))
    train_start = Column(Date)
    train_end = Column(Date)
    valid_start = Column(Date)
    valid_end = Column(Date)
    test_start = Column(Date)
    test_end = Column(Date)
    prediction_date = Column(Date)
    status = Column(String(20), nullable=False, default="draft")
    progress = Column(Integer, nullable=False, default=0)
    parameters = Column(JSONB, nullable=False, default=json_object)
    split_config = Column(JSONB, nullable=False, default=json_object)
    feature_config = Column(JSONB, nullable=False, default=json_object)
    target_config = Column(JSONB, nullable=False, default=json_object)
    metrics = Column(JSONB, nullable=False, default=json_object)
    feature_importance = Column(JSONB, nullable=False, default=json_object)
    artifact_uri = Column(Text)
    artifact_digest = Column(String(64))
    artifact_size = Column(BigInteger)
    code_commit = Column(String(64))
    warnings = Column(JSONB, nullable=False, default=json_array)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("run_type IN ('train','backtest','predict','walk_forward')", name="ck_model_run_type"),
        CheckConstraint(
            "status IN ('draft','training','candidate','production','retired','failed')", name="ck_model_run_status"
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_model_run_progress"),
        Index("ix_model_run_lookup", "market", "model_key", "status", "created_at"),
        Index(
            "uix_model_run_production_market_key",
            "market",
            "model_key",
            unique=True,
            postgresql_where=text("status = 'production'"),
        ),
    )


class ModelPublication(Base):
    __tablename__ = "model_publication"
    id = Column(BigInteger, primary_key=True)
    model_run_id = Column(BigInteger, ForeignKey("model_run.id", ondelete="RESTRICT"), nullable=False)
    previous_model_run_id = Column(BigInteger, ForeignKey("model_run.id", ondelete="SET NULL"))
    published_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class ModelSignal(Base):
    __tablename__ = "model_signal"
    id = Column(BigInteger, primary_key=True)
    trade_date = Column(Date, nullable=False)
    instrument_id = Column(Integer, ForeignKey("instrument.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(32), nullable=False)
    market = Column(String(8), nullable=False)
    universe_id = Column(Integer, ForeignKey("universe.id", ondelete="RESTRICT"), nullable=False)
    model_version = Column(String(96), nullable=False)
    market_score = Column(Float)
    time_series_score = Column(Float)
    cross_section_score = Column(Float)
    risk_penalty = Column(Float, nullable=False, default=0)
    final_score = Column(Float, nullable=False)
    universe_rank = Column(Integer)
    predicted_return = Column(Float)
    signal = Column(String(16), nullable=False)
    reasons = Column(JSONB, nullable=False, default=json_array)
    score_components = Column(JSONB, nullable=False, default=json_object)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint(
            "market",
            "universe_id",
            "trade_date",
            "instrument_id",
            "model_version",
            name="uix_model_signal_market_universe",
        ),
        Index("ix_model_signal_ranking", "market", "universe_id", "trade_date", "universe_rank"),
    )


class PortfolioRecommendation(Base):
    __tablename__ = "portfolio_recommendation"
    id = Column(BigInteger, primary_key=True)
    trade_date = Column(Date, nullable=False)
    market = Column(String(8), nullable=False)
    universe_id = Column(Integer, ForeignKey("universe.id", ondelete="RESTRICT"), nullable=False)
    model_version = Column(String(96), nullable=False)
    market_regime_id = Column(BigInteger, ForeignKey("market_regime_snapshot.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(20), nullable=False, default="ready")
    max_equity_exposure = Column(Float, nullable=False)
    target_equity_exposure = Column(Float, nullable=False)
    config = Column(JSONB, nullable=False, default=json_object)
    summary = Column(JSONB, nullable=False, default=json_object)
    warnings = Column(JSONB, nullable=False, default=json_array)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    items = relationship("PortfolioRecommendationItem", cascade="all, delete-orphan", back_populates="recommendation")
    __table_args__ = (
        UniqueConstraint("trade_date", "universe_id", "model_version", name="uix_portfolio_recommendation"),
    )


class PortfolioRecommendationItem(Base):
    __tablename__ = "portfolio_recommendation_item"
    id = Column(BigInteger, primary_key=True)
    recommendation_id = Column(
        BigInteger, ForeignKey("portfolio_recommendation.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id = Column(Integer, ForeignKey("instrument.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(32), nullable=False)
    rank = Column(Integer, nullable=False)
    target_weight = Column(Float, nullable=False, default=0)
    final_score = Column(Float, nullable=False)
    predicted_return = Column(Float)
    signal = Column(String(16), nullable=False)
    reasons = Column(JSONB, nullable=False, default=json_array)
    constraints = Column(JSONB, nullable=False, default=json_object)
    recommendation = relationship("PortfolioRecommendation", back_populates="items")
    __table_args__ = (
        UniqueConstraint("recommendation_id", "instrument_id", name="uix_portfolio_item"),
    )


QUANT_TABLES = (
    QuantDatasetSnapshot,
    MarketRegimeSnapshot,
    ModelDefinition,
    ModelRun,
    ModelPublication,
    ModelSignal,
    PortfolioRecommendation,
    PortfolioRecommendationItem,
)
